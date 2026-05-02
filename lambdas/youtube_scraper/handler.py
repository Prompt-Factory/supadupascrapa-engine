import json
import math
import os
from typing import Any

from utils import (
    JsonlOutputWriter,
    build_chart_hit_records,
    build_channel_snapshot_records,
    build_run_id,
    build_video_snapshot_records,
    is_running_in_lambda,
    load_local_env_if_present,
    utc_now_iso,
)
from v3_region_config import (
    V3_ESTIMATED_DAILY_QUOTA_HEADROOM,
    V3_REGION_PLANS,
    V3_TOTAL_ESTIMATED_UNITS,
    V3_TOTAL_TARGET_VIDEOS,
    YOUTUBE_V3_PAGE_SIZE,
)
from youtube_client import (
    fetch_channel_snapshots,
    fetch_most_popular_page,
)


def get_region_plan(region_code: str):
    normalized_code = region_code.upper()
    for plan in V3_REGION_PLANS:
        if plan["code"] == normalized_code:
            return plan
    return None


def get_int_event_value(
    event: dict[str, Any],
    field_name: str,
    default_value: int,
    *,
    min_value: int,
    max_value: int | None = None,
) -> int:
    raw_value = event.get(field_name, default_value)
    value = int(raw_value)
    if value < min_value:
        raise ValueError(f"{field_name} must be >= {min_value}")
    if max_value is not None and value > max_value:
        raise ValueError(f"{field_name} must be <= {max_value}")
    return value


def build_overview_response() -> dict[str, Any]:
    return {
        "statusCode": 200,
        "generatedAt": utc_now_iso(),
        "version": "v3-mostPopular",
        "regions": V3_REGION_PLANS,
        "summary": {
            "regionCount": len(V3_REGION_PLANS),
            "totalTargetVideos": V3_TOTAL_TARGET_VIDEOS,
            "totalEstimatedUnits": V3_TOTAL_ESTIMATED_UNITS,
            "estimatedQuotaHeadroom": V3_ESTIMATED_DAILY_QUOTA_HEADROOM,
        },
    }


def scrape_scope(
    *,
    api_key: str,
    writer: JsonlOutputWriter | None,
    region_code: str,
    collected_at: str,
    run_id: str,
    chart_scope: str,
    requested_video_category_id: str | None,
    requested_video_category_label: str | None,
    target_videos: int,
    max_results: int,
    max_pages_per_scope: int | None,
    include_channel_snapshots: bool,
) -> dict[str, Any]:
    target_pages = math.ceil(target_videos / max_results)
    if max_pages_per_scope is not None:
        target_pages = min(target_pages, max_pages_per_scope)

    page_number = 1
    page_token = None
    chart_hit_count = 0
    video_snapshot_count = 0
    channel_snapshot_count = 0
    api_call_count = 0
    fetched_pages = 0

    while page_number <= target_pages:
        status_code, response_body = fetch_most_popular_page(
            api_key=api_key,
            region_code=region_code,
            max_results=max_results,
            page_token=page_token,
            video_category_id=requested_video_category_id,
        )
        api_call_count += 1
        if status_code != 200:
            return {
                "statusCode": status_code,
                "chartScope": chart_scope,
                "videoCategoryId": requested_video_category_id,
                "videoCategoryLabel": requested_video_category_label,
                "targetVideos": target_videos,
                "targetPages": target_pages,
                "fetchedPages": fetched_pages,
                "chartHitCount": chart_hit_count,
                "videoSnapshotCount": video_snapshot_count,
                "channelSnapshotCount": channel_snapshot_count,
                "apiCallCount": api_call_count,
                "error": response_body.get("error"),
            }

        items = response_body.get("items", [])
        if not items:
            break

        chart_hit_records = build_chart_hit_records(
            items=items,
            region_code=region_code,
            collected_at=collected_at,
            run_id=run_id,
            chart_scope=chart_scope,
            requested_video_category_id=requested_video_category_id,
            requested_video_category_label=requested_video_category_label,
            page_number=page_number,
            max_results=max_results,
        )
        video_snapshot_records = build_video_snapshot_records(
            items=items,
            region_code=region_code,
            collected_at=collected_at,
            run_id=run_id,
            chart_scope=chart_scope,
            requested_video_category_id=requested_video_category_id,
            requested_video_category_label=requested_video_category_label,
            page_number=page_number,
            max_results=max_results,
        )

        if writer:
            writer.write_jsonl_records("chart_hits", chart_hit_records)
            writer.write_jsonl_records(
                "video_snapshots",
                video_snapshot_records,
            )

        chart_hit_count += len(chart_hit_records)
        video_snapshot_count += len(video_snapshot_records)
        fetched_pages += 1

        if include_channel_snapshots:
            channel_ids = [
                item.get("snippet", {}).get("channelId")
                for item in items
                if item.get("snippet", {}).get("channelId")
            ]
            channel_status, channel_body = fetch_channel_snapshots(
                api_key=api_key,
                channel_ids=channel_ids,
            )
            api_call_count += 1
            if channel_status != 200:
                return {
                    "statusCode": channel_status,
                    "chartScope": chart_scope,
                    "videoCategoryId": requested_video_category_id,
                    "videoCategoryLabel": requested_video_category_label,
                    "targetVideos": target_videos,
                    "targetPages": target_pages,
                    "fetchedPages": fetched_pages,
                    "chartHitCount": chart_hit_count,
                    "videoSnapshotCount": video_snapshot_count,
                    "channelSnapshotCount": channel_snapshot_count,
                    "apiCallCount": api_call_count,
                    "error": channel_body.get("error"),
                }

            channel_records = build_channel_snapshot_records(
                items=channel_body.get("items", []),
                region_code=region_code,
                collected_at=collected_at,
                run_id=run_id,
                chart_scope=chart_scope,
                requested_video_category_id=requested_video_category_id,
                requested_video_category_label=requested_video_category_label,
                page_number=page_number,
            )
            if writer:
                writer.write_jsonl_records(
                    "channel_snapshots",
                    channel_records,
                )
            channel_snapshot_count += len(channel_records)

        page_token = response_body.get("nextPageToken")
        if not page_token:
            break
        page_number += 1

    return {
        "statusCode": 200,
        "chartScope": chart_scope,
        "videoCategoryId": requested_video_category_id,
        "videoCategoryLabel": requested_video_category_label,
        "targetVideos": target_videos,
        "targetPages": target_pages,
        "fetchedPages": fetched_pages,
        "chartHitCount": chart_hit_count,
        "videoSnapshotCount": video_snapshot_count,
        "channelSnapshotCount": channel_snapshot_count,
        "apiCallCount": api_call_count,
    }


def handler(event, context):
    event = event or {}
    load_local_env_if_present()
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise ValueError("YOUTUBE_API_KEY is not set")

    region_code = event.get("regionCode")
    if not region_code:
        response = build_overview_response()
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return response

    region_plan = get_region_plan(region_code)
    if not region_plan:
        response = {
            "statusCode": 404,
            "generatedAt": utc_now_iso(),
            "error": {"message": f"Unknown regionCode: {region_code}"},
        }
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return response

    max_results = get_int_event_value(
        event,
        "maxResults",
        YOUTUBE_V3_PAGE_SIZE,
        min_value=1,
        max_value=50,
    )
    max_pages_per_scope_raw = event.get("maxPagesPerScope")
    max_pages_per_scope = (
        int(max_pages_per_scope_raw)
        if max_pages_per_scope_raw is not None
        else None
    )
    if max_pages_per_scope is not None and max_pages_per_scope < 1:
        raise ValueError("maxPagesPerScope must be >= 1")

    include_overall_chart = event.get("includeOverallChart", True)
    include_category_charts = event.get("includeCategoryCharts", True)
    include_channel_snapshots = event.get(
        "includeChannelSnapshots",
        True,
    )
    save_to_file = event.get("saveToFile", not is_running_in_lambda())
    save_split_files = event.get("saveSplitFiles", save_to_file)
    save_bundle_file = event.get("saveBundleFile", save_to_file)
    output_dir = event.get("outputDir", "outputs/youtube_scraper")

    collected_at = utc_now_iso()
    run_id = build_run_id(region_plan["code"], collected_at)
    writer = (
        JsonlOutputWriter(
            output_dir=output_dir,
            region_code=region_plan["code"],
            run_id=run_id,
            collected_at=collected_at,
        )
        if save_to_file and save_split_files
        else None
    )

    try:
        scope_summaries: list[dict[str, Any]] = []
        scope_errors: list[dict[str, Any]] = []
        total_chart_hits = 0
        total_video_snapshots = 0
        total_channel_snapshots = 0
        total_api_calls = 0
        successful_scope_count = 0

        if include_overall_chart:
            overall_summary = scrape_scope(
                api_key=api_key,
                writer=writer,
                region_code=region_plan["code"],
                collected_at=collected_at,
                run_id=run_id,
                chart_scope="overall",
                requested_video_category_id=None,
                requested_video_category_label=None,
                target_videos=region_plan["overall_target_videos"],
                max_results=max_results,
                max_pages_per_scope=max_pages_per_scope,
                include_channel_snapshots=include_channel_snapshots,
            )
            scope_summaries.append(overall_summary)
            if overall_summary["statusCode"] != 200:
                scope_errors.append(overall_summary)
            else:
                successful_scope_count += 1
                total_chart_hits += overall_summary["chartHitCount"]
                total_video_snapshots += overall_summary[
                    "videoSnapshotCount"
                ]
                total_channel_snapshots += overall_summary[
                    "channelSnapshotCount"
                ]
            total_api_calls += overall_summary["apiCallCount"]

        if include_category_charts:
            for allocation in region_plan["category_allocations"]:
                category_summary = scrape_scope(
                    api_key=api_key,
                    writer=writer,
                    region_code=region_plan["code"],
                    collected_at=collected_at,
                    run_id=run_id,
                    chart_scope="category",
                    requested_video_category_id=allocation["id"],
                    requested_video_category_label=allocation["label"],
                    target_videos=allocation["target_videos"],
                    max_results=max_results,
                    max_pages_per_scope=max_pages_per_scope,
                    include_channel_snapshots=include_channel_snapshots,
                )
                scope_summaries.append(category_summary)
                if category_summary["statusCode"] != 200:
                    scope_errors.append(category_summary)
                else:
                    successful_scope_count += 1
                    total_chart_hits += category_summary["chartHitCount"]
                    total_video_snapshots += category_summary[
                        "videoSnapshotCount"
                    ]
                    total_channel_snapshots += category_summary[
                        "channelSnapshotCount"
                    ]
                total_api_calls += category_summary["apiCallCount"]

        final_status_code = 200 if successful_scope_count > 0 else 502
        response = {
            "statusCode": final_status_code,
            "generatedAt": utc_now_iso(),
            "version": "v3-mostPopular",
            "regionPlan": region_plan,
            "request": {
                "regionCode": region_plan["code"],
                "collectedAt": collected_at,
                "runId": run_id,
                "maxResults": max_results,
                "maxPagesPerScope": max_pages_per_scope,
                "includeOverallChart": include_overall_chart,
                "includeCategoryCharts": include_category_charts,
                "includeChannelSnapshots": include_channel_snapshots,
                "outputDir": output_dir,
            },
            "scopeSummaries": scope_summaries,
            "scopeErrors": scope_errors,
            "summary": {
                "scopeCount": len(scope_summaries),
                "successfulScopeCount": successful_scope_count,
                "failedScopeCount": len(scope_errors),
                "chartHitCount": total_chart_hits,
                "videoSnapshotCount": total_video_snapshots,
                "channelSnapshotCount": total_channel_snapshots,
                "apiCallCount": total_api_calls,
            },
            "savedFiles": (
                writer.build_saved_files_payload(
                    include_bundle=save_bundle_file
                )
                if writer
                else {}
            ),
        }

        if writer and save_bundle_file:
            writer.write_bundle(response)
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return response
    finally:
        if writer:
            writer.close()


if __name__ == "__main__":
    sample_event_path = os.path.join(
        os.path.dirname(__file__),
        "sample_event.json",
    )
    event: dict[str, Any] = {}
    if os.path.exists(sample_event_path):
        with open(sample_event_path, encoding="utf-8") as sample_file:
            event = json.load(sample_file)
    handler(event, None)
