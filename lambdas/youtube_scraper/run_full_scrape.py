import argparse
import time

from handler import handler
from v3_region_config import V3_REGION_PLANS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run V3 mostPopular scrape for configured regions.",
    )
    parser.add_argument(
        "--region-code",
        help="Run only one region code, e.g. KR",
    )
    parser.add_argument(
        "--max-pages-per-scope",
        type=int,
        help="Limit page count per scope for testing.",
    )
    parser.add_argument(
        "--log-every-pages",
        type=int,
        help="Print page-level progress every N pages.",
    )
    parser.add_argument(
        "--skip-save",
        action="store_true",
        help="Do not write output files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    targets = V3_REGION_PLANS
    if args.region_code:
        targets = [
            plan
            for plan in V3_REGION_PLANS
            if plan["code"] == args.region_code.upper()
        ]
        if not targets:
            raise SystemExit(f"Unknown region code: {args.region_code}")

    batch_started_at = time.time()
    total_regions = len(targets)
    ok_count = 0
    fail_count = 0

    for index, plan in enumerate(targets, start=1):
        started_at = time.time()
        print()
        print(
            f"=== Region {index}/{total_regions}: {plan['code']} "
            f"(tier {plan['tier']}) ==="
        )
        print(
            f"target={plan['daily_target_videos']} "
            f"overall={plan['overall_target_videos']} "
            f"category={plan['category_target_videos']} "
            f"allocations={len(plan['category_allocations'])}"
        )
        event = {
            "regionCode": plan["code"],
            "logProgress": True,
            "printResponse": False,
            "saveToFile": not args.skip_save,
            "saveSplitFiles": not args.skip_save,
            "saveBundleFile": not args.skip_save,
        }
        if args.max_pages_per_scope:
            event["maxPagesPerScope"] = args.max_pages_per_scope
        if args.log_every_pages:
            event["logEveryPages"] = args.log_every_pages

        response = handler(event, None)
        status_code = response.get("statusCode")
        elapsed = time.time() - started_at
        summary = response.get("summary", {})
        if status_code == 200:
            ok_count += 1
        else:
            fail_count += 1

        print(
            f"batchProgress ok={ok_count} fail={fail_count} "
            f"lastRegion={plan['code']} "
            f"status={status_code} "
            f"scopeFail={summary.get('failedScopeCount', 0)} "
            f"videos={summary.get('videoSnapshotCount', 0)} "
            f"dupVideos={summary.get('duplicateVideoSkipCount', 0)} "
            f"dupChannels={summary.get('duplicateChannelSkipCount', 0)} "
            f"apiCalls={summary.get('apiCallCount', 0)} "
            f"elapsed={elapsed:.1f}s"
        )

    total_elapsed = time.time() - batch_started_at
    print()
    print(
        f"completed regions={total_regions} ok={ok_count} fail={fail_count} "
        f"elapsed={total_elapsed:.1f}s"
    )


if __name__ == "__main__":
    main()
