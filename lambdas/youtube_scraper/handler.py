import json
import math
import os
import time
from typing import Any

from broad_search_seed_config import (
    BROAD_SEARCH_REGION_PLANS,
)
from utils import (
    JsonlOutputWriter,
    build_chart_hit_records,
    build_channel_snapshot_records,
    create_output_writer,
    build_search_hit_records,
    build_run_id,
    build_video_snapshot_records,
    is_running_in_lambda,
    load_local_env_if_present,
    utc_days_ago_iso,
    utc_now_iso,
    write_batch_summary_payload,
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
    fetch_search_page,
    fetch_video_snapshots,
)


SCRAPER_VERSION = "v3.1"


def get_region_plan(region_code: str):
    normalized_code = region_code.upper()
    for plan in V3_REGION_PLANS:
        if plan["code"] == normalized_code:
            return plan
    return None


def get_broad_search_region_plan(region_code: str):
    return BROAD_SEARCH_REGION_PLANS.get(region_code.upper())


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
        "version": SCRAPER_VERSION,
        "regions": V3_REGION_PLANS,
        "summary": {
            "regionCount": len(V3_REGION_PLANS),
            "totalTargetVideos": V3_TOTAL_TARGET_VIDEOS,
            "totalEstimatedUnits": V3_TOTAL_ESTIMATED_UNITS,
            "estimatedQuotaHeadroom": V3_ESTIMATED_DAILY_QUOTA_HEADROOM,
        },
    }


def build_scope_name(
    chart_scope: str,
    requested_video_category_id: str | None,
    requested_video_category_label: str | None,
) -> str:
    if chart_scope == "overall":
        return "overall"
    if requested_video_category_id and requested_video_category_label:
        return (
            f"category {requested_video_category_id} "
            f"{requested_video_category_label}"
        )
    if requested_video_category_id:
        return f"category {requested_video_category_id}"
    return chart_scope


def build_search_scope_name(
    search_seed_code: str,
    search_seed_label: str,
    source_query: str,
) -> str:
    return (
        f"search {search_seed_code} "
        f"{search_seed_label} "
        f"query={source_query}"
    )


def extract_error_summary(response_body: dict[str, Any]) -> str:
    error = response_body.get("error", {})
    details = error.get("errors", [])
    reason = ""
    if details:
        reason = details[0].get("reason", "")
    message = error.get("message", "")
    if reason and message:
        return f"{reason}: {message}"
    return reason or message or "unknown error"


def get_log_every_pages(
    target_pages: int,
    configured_value: int | None,
) -> int:
    if configured_value is not None:
        return max(1, configured_value)
    if target_pages <= 10:
        return 1
    if target_pages <= 100:
        return 10
    if target_pages <= 500:
        return 25
    if target_pages <= 1000:
        return 50
    return 100


def should_log_page_progress(
    page_number: int,
    target_pages: int,
    log_every_pages: int,
) -> bool:
    return (
        page_number == 1
        or page_number == target_pages
        or page_number % log_every_pages == 0
    )


def filter_new_video_snapshot_records(
    records: list[dict[str, Any]],
    seen_video_ids: set[str],
) -> tuple[list[dict[str, Any]], int]:
    new_records: list[dict[str, Any]] = []
    duplicate_count = 0
    for record in records:
        video_id = record.get("video_id")
        if not video_id:
            new_records.append(record)
            continue
        if video_id in seen_video_ids:
            duplicate_count += 1
            continue
        seen_video_ids.add(video_id)
        new_records.append(record)
    return new_records, duplicate_count


def filter_new_channel_ids(
    channel_ids: list[str],
    seen_channel_ids: set[str],
) -> tuple[list[str], int]:
    unique_channel_ids = list(dict.fromkeys(channel_ids))
    new_channel_ids: list[str] = []
    duplicate_count = 0
    for channel_id in unique_channel_ids:
        if channel_id in seen_channel_ids:
            duplicate_count += 1
            continue
        seen_channel_ids.add(channel_id)
        new_channel_ids.append(channel_id)
    return new_channel_ids, duplicate_count


def filter_new_search_video_ids(
    items: list[dict[str, Any]],
    seen_video_ids: set[str],
) -> tuple[list[str], int]:
    candidate_video_ids: list[str] = []
    duplicate_count = 0
    seen_in_page: set[str] = set()
    for item in items:
        item_id = item.get("id", {})
        video_id = item_id.get("videoId")
        if not video_id:
            continue
        if video_id in seen_in_page:
            duplicate_count += 1
            continue
        seen_in_page.add(video_id)
        if video_id in seen_video_ids:
            duplicate_count += 1
            continue
        candidate_video_ids.append(video_id)
    return candidate_video_ids, duplicate_count


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
    scope_index: int,
    total_scope_count: int,
    log_progress: bool,
    log_every_pages: int | None,
    seen_video_ids: set[str],
    seen_channel_ids: set[str],
) -> dict[str, Any]:
    scope_started_at = time.time()
    scope_name = build_scope_name(
        chart_scope,
        requested_video_category_id,
        requested_video_category_label,
    )
    target_pages = math.ceil(target_videos / max_results)
    if max_pages_per_scope is not None:
        target_pages = min(target_pages, max_pages_per_scope)
    effective_log_every_pages = get_log_every_pages(
        target_pages,
        log_every_pages,
    )

    if log_progress:
        print(
            f"  [scope {scope_index}/{total_scope_count}] start "
            f"{scope_name} "
            f"targetVideos={target_videos} "
            f"targetPages={target_pages}"
        )

    page_number = 1
    page_token = None
    chart_hit_count = 0
    video_snapshot_count = 0
    channel_snapshot_count = 0
    api_call_count = 0
    fetched_pages = 0
    duplicate_video_skip_count = 0
    duplicate_channel_skip_count = 0

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
            error_summary = extract_error_summary(response_body)
            if log_progress:
                print(
                    f"  [scope {scope_index}/{total_scope_count}] fail "
                    f"{scope_name} "
                    f"status={status_code} "
                    f"pages={fetched_pages}/{target_pages} "
                    f"apiCalls={api_call_count} "
                    f"error={error_summary}"
                )
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
                "duplicateVideoSkipCount": duplicate_video_skip_count,
                "duplicateChannelSkipCount": duplicate_channel_skip_count,
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
        (
            new_video_snapshot_records,
            duplicate_video_count_for_page,
        ) = filter_new_video_snapshot_records(
            video_snapshot_records,
            seen_video_ids,
        )
        duplicate_video_skip_count += duplicate_video_count_for_page

        if writer:
            writer.write_jsonl_records("chart_hits", chart_hit_records)
            writer.write_jsonl_records(
                "video_snapshots",
                new_video_snapshot_records,
            )

        chart_hit_count += len(chart_hit_records)
        video_snapshot_count += len(new_video_snapshot_records)
        fetched_pages += 1

        if include_channel_snapshots:
            channel_ids = [
                item.get("snippet", {}).get("channelId")
                for item in items
                if item.get("snippet", {}).get("channelId")
            ]
            (
                new_channel_ids,
                duplicate_channel_count_for_page,
            ) = filter_new_channel_ids(
                channel_ids,
                seen_channel_ids,
            )
            duplicate_channel_skip_count += (
                duplicate_channel_count_for_page
            )
            if new_channel_ids:
                channel_status, channel_body = fetch_channel_snapshots(
                    api_key=api_key,
                    channel_ids=new_channel_ids,
                )
                api_call_count += 1
                if channel_status != 200:
                    error_summary = extract_error_summary(channel_body)
                    if log_progress:
                        print(
                            f"  [scope {scope_index}/{total_scope_count}] fail "
                            f"{scope_name} "
                            f"status={channel_status} "
                            f"pages={fetched_pages}/{target_pages} "
                            f"apiCalls={api_call_count} "
                            f"error={error_summary}"
                        )
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
                        "duplicateVideoSkipCount": (
                            duplicate_video_skip_count
                        ),
                        "duplicateChannelSkipCount": (
                            duplicate_channel_skip_count
                        ),
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
                    requested_video_category_label=(
                        requested_video_category_label
                    ),
                    page_number=page_number,
                )
                if writer:
                    writer.write_jsonl_records(
                        "channel_snapshots",
                        channel_records,
                    )
                channel_snapshot_count += len(channel_records)

        if log_progress and should_log_page_progress(
            page_number,
            target_pages,
            effective_log_every_pages,
        ):
            progress_percent = min((page_number / target_pages) * 100, 100.0)
            start_rank = ((page_number - 1) * max_results) + 1
            end_rank = start_rank + len(items) - 1
            print(
                f"    page {page_number}/{target_pages} "
                f"{progress_percent:5.1f}% "
                f"rank={start_rank}-{end_rank} "
                f"hits={chart_hit_count} "
                f"videos={video_snapshot_count} "
                f"channels={channel_snapshot_count} "
                f"dupVideos={duplicate_video_skip_count} "
                f"dupChannels={duplicate_channel_skip_count}"
            )

        page_token = response_body.get("nextPageToken")
        if not page_token:
            break
        page_number += 1

    elapsed = time.time() - scope_started_at
    if log_progress:
        print(
            f"  [scope {scope_index}/{total_scope_count}] done "
            f"{scope_name} "
            f"pages={fetched_pages}/{target_pages} "
            f"hits={chart_hit_count} "
            f"videos={video_snapshot_count} "
            f"channels={channel_snapshot_count} "
            f"dupVideos={duplicate_video_skip_count} "
            f"dupChannels={duplicate_channel_skip_count} "
            f"apiCalls={api_call_count} "
            f"elapsed={elapsed:.1f}s"
        )

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
        "duplicateVideoSkipCount": duplicate_video_skip_count,
        "duplicateChannelSkipCount": duplicate_channel_skip_count,
        "apiCallCount": api_call_count,
    }


def scrape_search_scope(
    *,
    api_key: str,
    writer: JsonlOutputWriter | None,
    region_code: str,
    collected_at: str,
    run_id: str,
    query_language: str,
    source_query: str,
    search_seed_code: str,
    search_seed_group: str,
    search_seed_label: str,
    target_pages: int,
    max_results: int,
    published_after: str | None,
    include_channel_snapshots: bool,
    scope_index: int,
    total_scope_count: int,
    log_progress: bool,
    log_every_pages: int | None,
    seen_video_ids: set[str],
    seen_channel_ids: set[str],
) -> dict[str, Any]:
    scope_started_at = time.time()
    scope_name = build_search_scope_name(
        search_seed_code,
        search_seed_label,
        source_query,
    )
    effective_log_every_pages = get_log_every_pages(
        target_pages,
        log_every_pages,
    )

    if log_progress:
        print(
            f"  [scope {scope_index}/{total_scope_count}] start "
            f"{scope_name} "
            f"targetPages={target_pages}"
        )

    page_number = 1
    page_token = None
    search_hit_count = 0
    video_snapshot_count = 0
    channel_snapshot_count = 0
    duplicate_video_skip_count = 0
    duplicate_channel_skip_count = 0
    api_call_count = 0
    fetched_pages = 0

    while page_number <= target_pages:
        status_code, response_body = fetch_search_page(
            api_key=api_key,
            query=source_query,
            region_code=region_code,
            max_results=max_results,
            order="date",
            page_token=page_token,
            published_after=published_after,
            relevance_language=query_language,
        )
        api_call_count += 1
        if status_code != 200:
            error_summary = extract_error_summary(response_body)
            if log_progress:
                print(
                    f"  [scope {scope_index}/{total_scope_count}] fail "
                    f"{scope_name} "
                    f"status={status_code} "
                    f"pages={fetched_pages}/{target_pages} "
                    f"apiCalls={api_call_count} "
                    f"error={error_summary}"
                )
            return {
                "statusCode": status_code,
                "chartScope": "search",
                "searchSeedCode": search_seed_code,
                "searchSeedGroup": search_seed_group,
                "searchSeedLabel": search_seed_label,
                "sourceQuery": source_query,
                "targetPages": target_pages,
                "fetchedPages": fetched_pages,
                "searchHitCount": search_hit_count,
                "videoSnapshotCount": video_snapshot_count,
                "channelSnapshotCount": channel_snapshot_count,
                "duplicateVideoSkipCount": duplicate_video_skip_count,
                "duplicateChannelSkipCount": duplicate_channel_skip_count,
                "apiCallCount": api_call_count,
                "error": response_body.get("error"),
            }

        items = response_body.get("items", [])
        if not items:
            break

        search_hit_records = build_search_hit_records(
            items=items,
            region_code=region_code,
            collected_at=collected_at,
            run_id=run_id,
            search_seed_code=search_seed_code,
            search_seed_group=search_seed_group,
            search_seed_label=search_seed_label,
            query_language=query_language,
            source_query=source_query,
            search_order="date",
            published_after=published_after,
            page_number=page_number,
            max_results=max_results,
        )
        if writer:
            writer.write_jsonl_records("search_hits", search_hit_records)
        search_hit_count += len(search_hit_records)
        fetched_pages += 1

        (
            candidate_video_ids,
            duplicate_video_count_from_hits,
        ) = filter_new_search_video_ids(items, seen_video_ids)
        duplicate_video_skip_count += duplicate_video_count_from_hits

        if candidate_video_ids:
            video_status, video_body = fetch_video_snapshots(
                api_key=api_key,
                video_ids=candidate_video_ids,
            )
            api_call_count += 1
            if video_status != 200:
                error_summary = extract_error_summary(video_body)
                if log_progress:
                    print(
                        f"  [scope {scope_index}/{total_scope_count}] fail "
                        f"{scope_name} "
                        f"status={video_status} "
                        f"pages={fetched_pages}/{target_pages} "
                        f"apiCalls={api_call_count} "
                        f"error={error_summary}"
                    )
                return {
                    "statusCode": video_status,
                    "chartScope": "search",
                    "searchSeedCode": search_seed_code,
                    "searchSeedGroup": search_seed_group,
                    "searchSeedLabel": search_seed_label,
                    "sourceQuery": source_query,
                    "targetPages": target_pages,
                    "fetchedPages": fetched_pages,
                    "searchHitCount": search_hit_count,
                    "videoSnapshotCount": video_snapshot_count,
                    "channelSnapshotCount": channel_snapshot_count,
                    "duplicateVideoSkipCount": (
                        duplicate_video_skip_count
                    ),
                    "duplicateChannelSkipCount": (
                        duplicate_channel_skip_count
                    ),
                    "apiCallCount": api_call_count,
                    "error": video_body.get("error"),
                }

            video_snapshot_records = build_video_snapshot_records(
                items=video_body.get("items", []),
                region_code=region_code,
                collected_at=collected_at,
                run_id=run_id,
                chart_scope="search",
                requested_video_category_id=None,
                requested_video_category_label=search_seed_code,
                page_number=page_number,
                max_results=max_results,
                source="youtube.videos.list.byId",
            )
            (
                new_video_snapshot_records,
                duplicate_video_count_from_snapshots,
            ) = filter_new_video_snapshot_records(
                video_snapshot_records,
                seen_video_ids,
            )
            duplicate_video_skip_count += (
                duplicate_video_count_from_snapshots
            )
            if writer:
                writer.write_jsonl_records(
                    "video_snapshots",
                    new_video_snapshot_records,
                )
            video_snapshot_count += len(new_video_snapshot_records)

            if include_channel_snapshots:
                channel_ids = [
                    item.get("snippet", {}).get("channelId")
                    for item in video_body.get("items", [])
                    if item.get("snippet", {}).get("channelId")
                ]
                (
                    new_channel_ids,
                    duplicate_channel_count_for_page,
                ) = filter_new_channel_ids(channel_ids, seen_channel_ids)
                duplicate_channel_skip_count += (
                    duplicate_channel_count_for_page
                )
                if new_channel_ids:
                    channel_status, channel_body = fetch_channel_snapshots(
                        api_key=api_key,
                        channel_ids=new_channel_ids,
                    )
                    api_call_count += 1
                    if channel_status != 200:
                        error_summary = extract_error_summary(channel_body)
                        if log_progress:
                            print(
                                f"  [scope {scope_index}/{total_scope_count}] fail "
                                f"{scope_name} "
                                f"status={channel_status} "
                                f"pages={fetched_pages}/{target_pages} "
                                f"apiCalls={api_call_count} "
                                f"error={error_summary}"
                            )
                        return {
                            "statusCode": channel_status,
                            "chartScope": "search",
                            "searchSeedCode": search_seed_code,
                            "searchSeedGroup": search_seed_group,
                            "searchSeedLabel": search_seed_label,
                            "sourceQuery": source_query,
                            "targetPages": target_pages,
                            "fetchedPages": fetched_pages,
                            "searchHitCount": search_hit_count,
                            "videoSnapshotCount": (
                                video_snapshot_count
                            ),
                            "channelSnapshotCount": (
                                channel_snapshot_count
                            ),
                            "duplicateVideoSkipCount": (
                                duplicate_video_skip_count
                            ),
                            "duplicateChannelSkipCount": (
                                duplicate_channel_skip_count
                            ),
                            "apiCallCount": api_call_count,
                            "error": channel_body.get("error"),
                        }

                    channel_records = build_channel_snapshot_records(
                        items=channel_body.get("items", []),
                        region_code=region_code,
                        collected_at=collected_at,
                        run_id=run_id,
                        chart_scope="search",
                        requested_video_category_id=None,
                        requested_video_category_label=search_seed_code,
                        page_number=page_number,
                        source="youtube.channels.list",
                    )
                    if writer:
                        writer.write_jsonl_records(
                            "channel_snapshots",
                            channel_records,
                        )
                    channel_snapshot_count += len(channel_records)

        if log_progress and should_log_page_progress(
            page_number,
            target_pages,
            effective_log_every_pages,
        ):
            start_rank = ((page_number - 1) * max_results) + 1
            end_rank = start_rank + len(items) - 1
            progress_percent = min((page_number / target_pages) * 100, 100.0)
            print(
                f"    page {page_number}/{target_pages} "
                f"{progress_percent:5.1f}% "
                f"rank={start_rank}-{end_rank} "
                f"searchHits={search_hit_count} "
                f"videos={video_snapshot_count} "
                f"channels={channel_snapshot_count} "
                f"dupVideos={duplicate_video_skip_count} "
                f"dupChannels={duplicate_channel_skip_count}"
            )

        page_token = response_body.get("nextPageToken")
        if not page_token:
            break
        page_number += 1

    elapsed = time.time() - scope_started_at
    if log_progress:
        print(
            f"  [scope {scope_index}/{total_scope_count}] done "
            f"{scope_name} "
            f"pages={fetched_pages}/{target_pages} "
            f"searchHits={search_hit_count} "
            f"videos={video_snapshot_count} "
            f"channels={channel_snapshot_count} "
            f"dupVideos={duplicate_video_skip_count} "
            f"dupChannels={duplicate_channel_skip_count} "
            f"apiCalls={api_call_count} "
            f"elapsed={elapsed:.1f}s"
        )

    return {
        "statusCode": 200,
        "chartScope": "search",
        "searchSeedCode": search_seed_code,
        "searchSeedGroup": search_seed_group,
        "searchSeedLabel": search_seed_label,
        "sourceQuery": source_query,
        "targetPages": target_pages,
        "fetchedPages": fetched_pages,
        "searchHitCount": search_hit_count,
        "videoSnapshotCount": video_snapshot_count,
        "channelSnapshotCount": channel_snapshot_count,
        "duplicateVideoSkipCount": duplicate_video_skip_count,
        "duplicateChannelSkipCount": duplicate_channel_skip_count,
        "apiCallCount": api_call_count,
    }


def resolve_output_storage(event: dict[str, Any]) -> str:
    configured_storage = event.get("outputStorage")
    if configured_storage is None:
        if is_running_in_lambda() and os.getenv("OUTPUT_S3_BUCKET"):
            return "s3"
        return "local"
    normalized_storage = str(configured_storage).strip().lower()
    if normalized_storage not in {"local", "s3"}:
        raise ValueError(
            "outputStorage must be either 'local' or 's3'"
        )
    return normalized_storage


def get_target_region_plans(
    region_codes: list[str] | None = None,
) -> list[dict[str, Any]]:
    if not region_codes:
        return V3_REGION_PLANS
    requested_codes = {code.upper() for code in region_codes}
    targets = [
        plan
        for plan in V3_REGION_PLANS
        if plan["code"] in requested_codes
    ]
    missing_codes = sorted(requested_codes - {plan["code"] for plan in targets})
    if missing_codes:
        raise ValueError(f"Unknown region codes: {missing_codes}")
    return targets


def run_region_scrape(
    *,
    event: dict[str, Any],
    api_key: str,
    region_plan: dict[str, Any],
) -> dict[str, Any]:
    print_response = event.get("printResponse", False)
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
    include_search_lane = event.get("includeSearchLane", True)
    include_channel_snapshots = event.get(
        "includeChannelSnapshots",
        True,
    )
    log_progress = event.get("logProgress", not is_running_in_lambda())
    log_every_pages_raw = event.get("logEveryPages")
    log_every_pages = (
        int(log_every_pages_raw) if log_every_pages_raw is not None else None
    )
    if log_every_pages is not None and log_every_pages < 1:
        raise ValueError("logEveryPages must be >= 1")
    search_lookback_days = get_int_event_value(
        event,
        "searchLookbackDays",
        7,
        min_value=1,
        max_value=365,
    )
    output_storage = resolve_output_storage(event)
    default_save_to_file = (
        True if output_storage == "s3" else not is_running_in_lambda()
    )
    save_to_file = event.get("saveToFile", default_save_to_file)
    save_split_files = event.get("saveSplitFiles", save_to_file)
    save_bundle_file = event.get("saveBundleFile", save_to_file)
    output_dir = event.get("outputDir", "outputs/youtube_scraper")
    output_s3_bucket = (
        event.get("outputS3Bucket") or os.getenv("OUTPUT_S3_BUCKET")
    )
    output_s3_prefix = (
        event.get("outputS3Prefix")
        or os.getenv("OUTPUT_S3_PREFIX")
        or "youtube_scraper/"
    )

    collected_at = utc_now_iso()
    run_id = build_run_id(region_plan["code"], collected_at)
    writer = (
        create_output_writer(
            output_storage=output_storage,
            output_dir=output_dir,
            region_code=region_plan["code"],
            run_id=run_id,
            collected_at=collected_at,
            s3_bucket=output_s3_bucket,
            s3_prefix=output_s3_prefix,
        )
        if save_to_file and save_split_files
        else None
    )
    broad_search_region_plan = get_broad_search_region_plan(
        region_plan["code"]
    )
    total_scope_count = 0
    if include_overall_chart:
        total_scope_count += 1
    if include_category_charts:
        total_scope_count += len(region_plan["category_allocations"])
    if include_search_lane and broad_search_region_plan:
        total_scope_count += len(broad_search_region_plan["seeds"])

    try:
        if log_progress:
            print(
                f"[region {region_plan['code']}] start "
                f"tier={region_plan['tier']} "
                f"target={region_plan['daily_target_videos']} "
                f"overall={region_plan['overall_target_videos']} "
                f"category={region_plan['category_target_videos']} "
                f"searchPages="
                f"{broad_search_region_plan['total_target_pages'] if broad_search_region_plan else 0} "
                f"scopes={total_scope_count}"
            )

        scope_summaries: list[dict[str, Any]] = []
        scope_errors: list[dict[str, Any]] = []
        total_chart_hits = 0
        total_search_hits = 0
        total_video_snapshots = 0
        total_channel_snapshots = 0
        total_duplicate_video_skips = 0
        total_duplicate_channel_skips = 0
        total_api_calls = 0
        successful_scope_count = 0
        scope_index = 0
        seen_video_ids: set[str] = set()
        seen_channel_ids: set[str] = set()

        if include_overall_chart:
            scope_index += 1
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
                scope_index=scope_index,
                total_scope_count=total_scope_count,
                log_progress=log_progress,
                log_every_pages=log_every_pages,
                seen_video_ids=seen_video_ids,
                seen_channel_ids=seen_channel_ids,
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
                total_duplicate_video_skips += overall_summary.get(
                    "duplicateVideoSkipCount",
                    0,
                )
                total_duplicate_channel_skips += overall_summary.get(
                    "duplicateChannelSkipCount",
                    0,
                )
            total_api_calls += overall_summary["apiCallCount"]

        if include_category_charts:
            for allocation in region_plan["category_allocations"]:
                scope_index += 1
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
                    scope_index=scope_index,
                    total_scope_count=total_scope_count,
                    log_progress=log_progress,
                    log_every_pages=log_every_pages,
                    seen_video_ids=seen_video_ids,
                    seen_channel_ids=seen_channel_ids,
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
                    total_duplicate_video_skips += category_summary.get(
                        "duplicateVideoSkipCount",
                        0,
                    )
                    total_duplicate_channel_skips += category_summary.get(
                        "duplicateChannelSkipCount",
                        0,
                    )
                total_api_calls += category_summary["apiCallCount"]

        if include_search_lane:
            if not broad_search_region_plan:
                raise ValueError(
                    f"No broad search plan for region {region_plan['code']}"
                )
            published_after = utc_days_ago_iso(search_lookback_days)
            for seed in broad_search_region_plan["seeds"]:
                scope_index += 1
                target_pages = seed["target_pages"]
                if max_pages_per_scope is not None:
                    target_pages = min(target_pages, max_pages_per_scope)
                search_summary = scrape_search_scope(
                    api_key=api_key,
                    writer=writer,
                    region_code=region_plan["code"],
                    collected_at=collected_at,
                    run_id=run_id,
                    query_language=broad_search_region_plan["language"],
                    source_query=seed["primary_query"],
                    search_seed_code=seed["code"],
                    search_seed_group=seed["group"],
                    search_seed_label=seed["label"]["ko"],
                    target_pages=target_pages,
                    max_results=max_results,
                    published_after=published_after,
                    include_channel_snapshots=include_channel_snapshots,
                    scope_index=scope_index,
                    total_scope_count=total_scope_count,
                    log_progress=log_progress,
                    log_every_pages=log_every_pages,
                    seen_video_ids=seen_video_ids,
                    seen_channel_ids=seen_channel_ids,
                )
                scope_summaries.append(search_summary)
                if search_summary["statusCode"] != 200:
                    scope_errors.append(search_summary)
                else:
                    successful_scope_count += 1
                    total_search_hits += search_summary.get(
                        "searchHitCount",
                        0,
                    )
                    total_video_snapshots += search_summary[
                        "videoSnapshotCount"
                    ]
                    total_channel_snapshots += search_summary[
                        "channelSnapshotCount"
                    ]
                    total_duplicate_video_skips += search_summary.get(
                        "duplicateVideoSkipCount",
                        0,
                    )
                    total_duplicate_channel_skips += search_summary.get(
                        "duplicateChannelSkipCount",
                        0,
                    )
                total_api_calls += search_summary["apiCallCount"]

        final_status_code = 200 if successful_scope_count > 0 else 502
        response = {
            "statusCode": final_status_code,
            "generatedAt": utc_now_iso(),
            "version": SCRAPER_VERSION,
            "regionPlan": region_plan,
            "request": {
                "regionCode": region_plan["code"],
                "collectedAt": collected_at,
                "runId": run_id,
                "maxResults": max_results,
                "maxPagesPerScope": max_pages_per_scope,
                "includeOverallChart": include_overall_chart,
                "includeCategoryCharts": include_category_charts,
                "includeSearchLane": include_search_lane,
                "includeChannelSnapshots": include_channel_snapshots,
                "searchLookbackDays": search_lookback_days,
                "logProgress": log_progress,
                "logEveryPages": log_every_pages,
                "outputStorage": output_storage,
                "outputDir": output_dir,
                "outputS3Bucket": output_s3_bucket,
                "outputS3Prefix": output_s3_prefix,
            },
            "scopeSummaries": scope_summaries,
            "scopeErrors": scope_errors,
            "summary": {
                "scopeCount": len(scope_summaries),
                "successfulScopeCount": successful_scope_count,
                "failedScopeCount": len(scope_errors),
                "chartHitCount": total_chart_hits,
                "searchHitCount": total_search_hits,
                "videoSnapshotCount": total_video_snapshots,
                "channelSnapshotCount": total_channel_snapshots,
                "duplicateVideoSkipCount": total_duplicate_video_skips,
                "duplicateChannelSkipCount": (
                    total_duplicate_channel_skips
                ),
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
        if log_progress:
            print(
                f"[region {region_plan['code']}] done "
                f"status={final_status_code} "
                f"scopeFail={len(scope_errors)} "
                f"chartHits={total_chart_hits} "
                f"searchHits={total_search_hits} "
                f"videos={total_video_snapshots} "
                f"channels={total_channel_snapshots} "
                f"dupVideos={total_duplicate_video_skips} "
                f"dupChannels={total_duplicate_channel_skips} "
                f"apiCalls={total_api_calls}"
            )
        if print_response:
            print(json.dumps(response, ensure_ascii=False, indent=2))
        return response
    finally:
        if writer:
            writer.close()


def run_batch_scrape(
    *,
    event: dict[str, Any],
    api_key: str,
) -> dict[str, Any]:
    print_response = event.get("printResponse", False)
    log_progress = event.get("logProgress", not is_running_in_lambda())
    output_storage = resolve_output_storage(event)
    default_save_to_file = (
        True if output_storage == "s3" else not is_running_in_lambda()
    )
    save_to_file = event.get("saveToFile", default_save_to_file)
    save_bundle_file = event.get("saveBundleFile", save_to_file)
    output_dir = event.get("outputDir", "outputs/youtube_scraper")
    output_s3_bucket = (
        event.get("outputS3Bucket") or os.getenv("OUTPUT_S3_BUCKET")
    )
    output_s3_prefix = (
        event.get("outputS3Prefix")
        or os.getenv("OUTPUT_S3_PREFIX")
        or "youtube_scraper/"
    )
    requested_region_codes = event.get("regionCodes")
    target_plans = get_target_region_plans(requested_region_codes)
    batch_collected_at = utc_now_iso()
    batch_run_id = build_run_id("ALL", batch_collected_at)
    total_regions = len(target_plans)
    ok_count = 0
    fail_count = 0
    total_chart_hits = 0
    total_search_hits = 0
    total_video_snapshots = 0
    total_channel_snapshots = 0
    total_duplicate_video_skips = 0
    total_duplicate_channel_skips = 0
    total_api_calls = 0
    region_results: list[dict[str, Any]] = []

    for index, plan in enumerate(target_plans, start=1):
        if log_progress:
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

        region_event = dict(event)
        region_event["regionCode"] = plan["code"]
        response = run_region_scrape(
            event=region_event,
            api_key=api_key,
            region_plan=plan,
        )
        region_results.append(response)
        summary = response.get("summary", {})
        status_code = response.get("statusCode", 502)
        if status_code == 200:
            ok_count += 1
        else:
            fail_count += 1

        total_chart_hits += summary.get("chartHitCount", 0)
        total_search_hits += summary.get("searchHitCount", 0)
        total_video_snapshots += summary.get("videoSnapshotCount", 0)
        total_channel_snapshots += summary.get("channelSnapshotCount", 0)
        total_duplicate_video_skips += summary.get(
            "duplicateVideoSkipCount",
            0,
        )
        total_duplicate_channel_skips += summary.get(
            "duplicateChannelSkipCount",
            0,
        )
        total_api_calls += summary.get("apiCallCount", 0)

        if log_progress:
            print(
                f"batchProgress ok={ok_count} fail={fail_count} "
                f"lastRegion={plan['code']} "
                f"status={status_code} "
                f"scopeFail={summary.get('failedScopeCount', 0)} "
                f"chartHits={summary.get('chartHitCount', 0)} "
                f"searchHits={summary.get('searchHitCount', 0)} "
                f"videos={summary.get('videoSnapshotCount', 0)} "
                f"dupVideos={summary.get('duplicateVideoSkipCount', 0)} "
                f"dupChannels={summary.get('duplicateChannelSkipCount', 0)} "
                f"apiCalls={summary.get('apiCallCount', 0)}"
            )

    final_status_code = 200 if ok_count > 0 else 502
    batch_response = {
        "statusCode": final_status_code,
        "generatedAt": utc_now_iso(),
        "version": SCRAPER_VERSION,
        "mode": "full-run",
        "request": {
            "runAllRegions": True,
            "regionCodes": requested_region_codes or [],
            "outputStorage": output_storage,
            "outputDir": output_dir,
            "outputS3Bucket": output_s3_bucket,
            "outputS3Prefix": output_s3_prefix,
        },
        "regionResults": region_results,
        "summary": {
            "regionCount": total_regions,
            "successfulRegionCount": ok_count,
            "failedRegionCount": fail_count,
            "chartHitCount": total_chart_hits,
            "searchHitCount": total_search_hits,
            "videoSnapshotCount": total_video_snapshots,
            "channelSnapshotCount": total_channel_snapshots,
            "duplicateVideoSkipCount": total_duplicate_video_skips,
            "duplicateChannelSkipCount": total_duplicate_channel_skips,
            "apiCallCount": total_api_calls,
        },
        "savedFiles": {},
    }
    if save_to_file and save_bundle_file:
        batch_summary_file = write_batch_summary_payload(
            output_storage=output_storage,
            output_dir=output_dir,
            collected_at=batch_collected_at,
            batch_run_id=batch_run_id,
            payload=batch_response,
            s3_bucket=output_s3_bucket,
            s3_prefix=output_s3_prefix,
        )
        batch_response["savedFiles"]["batchSummaryFile"] = (
            batch_summary_file
        )
    if log_progress:
        print()
        print(
            f"completed regions={total_regions} ok={ok_count} "
            f"fail={fail_count}"
        )
    if print_response:
        print(json.dumps(batch_response, ensure_ascii=False, indent=2))
    return batch_response


def handler(event, context):
    event = event or {}
    load_local_env_if_present()
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise ValueError("YOUTUBE_API_KEY is not set")

    if event.get("runAllRegions"):
        return run_batch_scrape(event=event, api_key=api_key)

    region_code = event.get("regionCode")
    if not region_code:
        response = build_overview_response()
        if event.get("printResponse", False):
            print(json.dumps(response, ensure_ascii=False, indent=2))
        return response

    region_plan = get_region_plan(region_code)
    if not region_plan:
        response = {
            "statusCode": 404,
            "generatedAt": utc_now_iso(),
            "error": {"message": f"Unknown regionCode: {region_code}"},
        }
        if event.get("printResponse", False):
            print(json.dumps(response, ensure_ascii=False, indent=2))
        return response

    return run_region_scrape(
        event=event,
        api_key=api_key,
        region_plan=region_plan,
    )


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
