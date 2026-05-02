import argparse
import io
import json
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from dotenv import load_dotenv

from config import (
    SCRAPE_TARGETS,
    YOUTUBE_DISCOVERY_LOOKBACK_DAYS,
    YOUTUBE_DISCOVERY_ORDER,
    YOUTUBE_LOCAL_OUTPUT_DIR,
    YOUTUBE_SEARCH_PAGE_SIZE,
    YOUTUBE_SEARCH_PAGES_PER_QUERY,
)
from handler import handler
from utils import resolve_output_dir
from youtube_client import build_published_after, utc_now_iso


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the YouTube scraper across configured targets."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only run the first N scrape targets.",
    )
    parser.add_argument(
        "--region-code",
        default="KR",
        help="YouTube regionCode to use for every target.",
    )
    parser.add_argument(
        "--output-dir",
        default=YOUTUBE_LOCAL_OUTPUT_DIR,
        help="Base output directory for split files and summaries.",
    )
    parser.add_argument(
        "--save-bundle-file",
        action="store_true",
        help="Also save per-target bundle files under runs/.",
    )
    return parser.parse_args()


def build_batch_summary_path(
    *,
    output_dir: str,
    started_at: str,
) -> Path:
    started_at_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    date_partition = started_at_dt.astimezone(timezone.utc).strftime(
        "%Y-%m-%d"
    )
    timestamp = started_at_dt.astimezone(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    return (
        resolve_output_dir(output_dir)
        / "batches"
        / f"date={date_partition}"
        / f"full_run_{timestamp}.json"
    )


def build_target_event(
    *,
    target: dict[str, Any],
    region_code: str,
    published_after: str,
    output_dir: str,
    save_bundle_file: bool,
) -> dict[str, Any]:
    return {
        "industry": target["client_industry_code"],
        "category": target["project_category_code"],
        "query": target["query"],
        "regionCode": region_code,
        "order": YOUTUBE_DISCOVERY_ORDER,
        "lookbackDays": YOUTUBE_DISCOVERY_LOOKBACK_DAYS,
        "publishedAfter": published_after,
        "maxResults": YOUTUBE_SEARCH_PAGE_SIZE,
        "pageCount": YOUTUBE_SEARCH_PAGES_PER_QUERY,
        "includeVideoSnapshots": True,
        "includeChannelSnapshots": True,
        "saveToFile": True,
        "saveSplitFiles": True,
        "saveBundleFile": save_bundle_file,
        "outputDir": output_dir,
    }


def run_target(event: dict[str, Any]) -> dict[str, Any]:
    handler_stdout = io.StringIO()
    with redirect_stdout(handler_stdout):
        return handler(event, None)


def format_elapsed(seconds: float) -> str:
    total_seconds = int(seconds)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def main() -> int:
    load_dotenv()
    args = parse_args()

    targets = SCRAPE_TARGETS[: args.limit] if args.limit else SCRAPE_TARGETS
    batch_started_at = utc_now_iso()
    published_after = build_published_after(
        YOUTUBE_DISCOVERY_LOOKBACK_DAYS
    )
    summary_path = build_batch_summary_path(
        output_dir=args.output_dir,
        started_at=batch_started_at,
    )
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "batch": {
            "startedAt": batch_started_at,
            "regionCode": args.region_code,
            "publishedAfter": published_after,
            "order": YOUTUBE_DISCOVERY_ORDER,
            "lookbackDays": YOUTUBE_DISCOVERY_LOOKBACK_DAYS,
            "maxResults": YOUTUBE_SEARCH_PAGE_SIZE,
            "pageCount": YOUTUBE_SEARCH_PAGES_PER_QUERY,
            "targetCount": len(targets),
            "saveBundleFile": args.save_bundle_file,
        },
        "results": [],
    }

    success_count = 0
    failure_count = 0
    empty_result_count = 0
    total_items = 0
    total_video_snapshots = 0
    total_channel_snapshots = 0
    batch_started_perf = perf_counter()

    print(
        (
            f"Starting full scrape: {len(targets)} targets, "
            f"{YOUTUBE_SEARCH_PAGE_SIZE * YOUTUBE_SEARCH_PAGES_PER_QUERY} "
            "results/target"
        ),
        flush=True,
    )
    print(
        f"Window: order={YOUTUBE_DISCOVERY_ORDER}, "
        f"publishedAfter={published_after}, region={args.region_code}",
        flush=True,
    )

    for index, target in enumerate(targets, start=1):
        event = build_target_event(
            target=target,
            region_code=args.region_code,
            published_after=published_after,
            output_dir=args.output_dir,
            save_bundle_file=args.save_bundle_file,
        )

        label = (
            f"{target['client_industry_code']} / "
            f"{target['project_category_code']}"
        )
        target_started_perf = perf_counter()
        print(
            (
                f"[{index}/{len(targets)} | "
                f"{(index / len(targets)) * 100:05.1f}% | "
                f"elapsed={format_elapsed(perf_counter() - batch_started_perf)}] "
                f"{label} -> {target['query']}"
            ),
            flush=True,
        )

        try:
            result = run_target(event)
            body = result.get("body", {})
            status_code = result.get("statusCode")
            item_summary = body.get("summary", {})
            success = status_code == 200
            items_fetched = item_summary.get("itemsFetched") or 0
            video_snapshot_count = (
                item_summary.get("videoSnapshotCount") or 0
            )
            channel_snapshot_count = (
                item_summary.get("channelSnapshotCount") or 0
            )

            if success:
                success_count += 1
                if items_fetched == 0:
                    empty_result_count += 1
                total_items += items_fetched
                total_video_snapshots += video_snapshot_count
                total_channel_snapshots += channel_snapshot_count
            else:
                failure_count += 1

            result_summary = {
                "client_industry_code": target["client_industry_code"],
                "client_industry_label": target["client_industry_label"],
                "project_category_code": target["project_category_code"],
                "project_category_label": target["project_category_label"],
                "query": target["query"],
                "statusCode": status_code,
                "itemsFetched": items_fetched,
                "videoSnapshotCount": video_snapshot_count,
                "channelSnapshotCount": channel_snapshot_count,
                "savedFiles": result.get("savedFiles", {}),
            }
            if not success:
                result_summary["error"] = body.get("error")
            summary["results"].append(result_summary)

            print(
                (
                    "  done "
                    f"status={status_code} "
                    f"items={items_fetched} "
                    f"videos={video_snapshot_count} "
                    f"channels={channel_snapshot_count} "
                    f"targetElapsed={format_elapsed(perf_counter() - target_started_perf)} "
                    f"ok={success_count} "
                    f"fail={failure_count} "
                    f"empty={empty_result_count} "
                    f"totals(items={total_items}, "
                    f"videos={total_video_snapshots}, "
                    f"channels={total_channel_snapshots})"
                ),
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            failure_count += 1
            summary["results"].append(
                {
                    "client_industry_code": target[
                        "client_industry_code"
                    ],
                    "client_industry_label": target[
                        "client_industry_label"
                    ],
                    "project_category_code": target[
                        "project_category_code"
                    ],
                    "project_category_label": target[
                        "project_category_label"
                    ],
                    "query": target["query"],
                    "statusCode": None,
                    "error": str(exc),
                }
            )
            print(
                (
                    f"  failed error={exc} "
                    f"targetElapsed={format_elapsed(perf_counter() - target_started_perf)} "
                    f"ok={success_count} fail={failure_count} "
                    f"empty={empty_result_count}"
                ),
                flush=True,
            )

        with summary_path.open("w", encoding="utf-8") as output_file:
            json.dump(summary, output_file, ensure_ascii=False, indent=2)
            output_file.write("\n")

    summary["batch"]["finishedAt"] = utc_now_iso()
    summary["batch"]["successCount"] = success_count
    summary["batch"]["failureCount"] = failure_count
    summary["batch"]["emptyResultCount"] = empty_result_count
    summary["batch"]["totalItemsFetched"] = total_items
    summary["batch"]["totalVideoSnapshots"] = total_video_snapshots
    summary["batch"]["totalChannelSnapshots"] = total_channel_snapshots
    summary["batch"]["elapsed"] = format_elapsed(
        perf_counter() - batch_started_perf
    )

    with summary_path.open("w", encoding="utf-8") as output_file:
        json.dump(summary, output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")

    print(
        (
            "Finished full scrape: "
            f"{success_count}/{len(targets)} succeeded, "
            f"{failure_count} failed, "
            f"{empty_result_count} empty. "
            f"Totals: items={total_items}, "
            f"videos={total_video_snapshots}, "
            f"channels={total_channel_snapshots}. "
            f"Summary: {summary_path}"
        ),
        flush=True,
    )
    return 0 if success_count == len(targets) else 1


if __name__ == "__main__":
    sys.exit(main())
