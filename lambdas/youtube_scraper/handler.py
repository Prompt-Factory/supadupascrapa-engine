import os
from dotenv import load_dotenv

from config import (
    YOUTUBE_DISCOVERY_LOOKBACK_DAYS,
    YOUTUBE_DISCOVERY_ORDER,
    YOUTUBE_LOCAL_OUTPUT_DIR,
    YOUTUBE_SEARCH_PAGE_SIZE,
    YOUTUBE_SEARCH_PAGES_PER_QUERY,
)
from youtube_client import (
    fetch_channel_snapshots,
    fetch_video_snapshots,
    search_discovery,
)
from utils import (
    build_channel_snapshot_records,
    build_search_hit_records,
    build_video_snapshot_records,
    is_running_in_lambda,
    save_json_output,
    save_jsonl_output,
)

# Load env from local .env file when running manually
if __name__ == "__main__":
    load_dotenv()


def get_int_event_value(
    event: dict,
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


def handler(event, context):
    event = event or {}
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise ValueError("YOUTUBE_API_KEY is not set")

    query = event.get("query", "브랜드필름")
    region_code = event.get("regionCode", "KR")
    industry = event.get("industry")
    category = event.get("category")
    order = event.get("order", YOUTUBE_DISCOVERY_ORDER)
    lookback_days = get_int_event_value(
        event,
        "lookbackDays",
        YOUTUBE_DISCOVERY_LOOKBACK_DAYS,
        min_value=1,
    )
    max_results = get_int_event_value(
        event,
        "maxResults",
        YOUTUBE_SEARCH_PAGE_SIZE,
        min_value=1,
        max_value=50,
    )
    page_count = get_int_event_value(
        event,
        "pageCount",
        YOUTUBE_SEARCH_PAGES_PER_QUERY,
        min_value=1,
    )
    published_after = event.get("publishedAfter")
    include_video_snapshots = event.get("includeVideoSnapshots", False)
    include_channel_snapshots = event.get(
        "includeChannelSnapshots",
        False,
    )
    save_to_file = event.get("saveToFile", not is_running_in_lambda())
    save_split_files = event.get("saveSplitFiles", save_to_file)
    save_bundle_file = event.get("saveBundleFile", save_to_file)
    output_dir = event.get("outputDir", YOUTUBE_LOCAL_OUTPUT_DIR)

    status_code, response_body = search_discovery(
        api_key=api_key,
        query=query,
        region_code=region_code,
        order=order,
        lookback_days=lookback_days,
        max_results=max_results,
        page_count=page_count,
        published_after=published_after,
    )

    if status_code == 200:
        request_meta = response_body.get("request", {})
        collected_at = request_meta.get("collectedAt")
        effective_published_after = request_meta.get("publishedAfter")
        search_items = response_body.get("items", [])

        if include_video_snapshots:
            video_status, video_response = fetch_video_snapshots(
                api_key=api_key,
                video_ids=[
                    item.get("videoId") for item in search_items
                ],
                query=query,
                region_code=region_code,
                industry=industry,
                category=category,
                order=order,
                published_after=effective_published_after,
                collected_at=collected_at,
            )
            response_body["videoSnapshots"] = video_response.get(
                "items",
                [],
            )
            response_body["summary"]["videoSnapshotCount"] = len(
                response_body["videoSnapshots"]
            )
            response_body["summary"]["videoSnapshotApiCalls"] = (
                video_response.get("apiCalls", 0)
            )
            if video_status != 200:
                response_body["videoSnapshotError"] = video_response.get(
                    "error"
                )

        if include_channel_snapshots:
            channel_status, channel_response = fetch_channel_snapshots(
                api_key=api_key,
                channel_ids=[
                    item.get("channelId") for item in search_items
                ],
                query=query,
                region_code=region_code,
                industry=industry,
                category=category,
                order=order,
                published_after=effective_published_after,
                collected_at=collected_at,
            )
            response_body["channelSnapshots"] = channel_response.get(
                "items",
                [],
            )
            response_body["summary"]["channelSnapshotCount"] = len(
                response_body["channelSnapshots"]
            )
            response_body["summary"]["channelSnapshotApiCalls"] = (
                channel_response.get("apiCalls", 0)
            )
            if channel_status != 200:
                response_body["channelSnapshotError"] = (
                    channel_response.get("error")
                )

    print("🔍 YouTube API Response:", status_code)
    print(response_body)

    request_meta = response_body.get("request", {})
    run_timestamp = request_meta.get("collectedAt")
    saved_files = {}

    if save_to_file and save_split_files:
        search_hit_records = build_search_hit_records(
            response_body.get("items", []),
            industry=industry,
            category=category,
        )
        saved_files["searchHitsFile"] = save_jsonl_output(
            query=query,
            region_code=region_code,
            records=search_hit_records,
            output_dir=output_dir,
            subdir="search_hits",
            run_timestamp=run_timestamp,
        )

        if include_video_snapshots:
            saved_files["videoSnapshotsFile"] = save_jsonl_output(
                query=query,
                region_code=region_code,
                records=build_video_snapshot_records(
                    response_body.get("videoSnapshots", [])
                ),
                output_dir=output_dir,
                subdir="video_snapshots",
                run_timestamp=run_timestamp,
            )

        if include_channel_snapshots:
            saved_files["channelSnapshotsFile"] = save_jsonl_output(
                query=query,
                region_code=region_code,
                records=build_channel_snapshot_records(
                    response_body.get("channelSnapshots", [])
                ),
                output_dir=output_dir,
                subdir="channel_snapshots",
                run_timestamp=run_timestamp,
            )

    if save_to_file and save_bundle_file:
        saved_files["bundleFile"] = save_json_output(
            query=query,
            region_code=region_code,
            status_code=status_code,
            response_body=response_body,
            output_dir=output_dir,
            run_timestamp=run_timestamp,
        )

    if saved_files:
        print("Saved local outputs:", saved_files)

    return {
        "statusCode": status_code,
        "body": response_body,
        "savedFile": saved_files.get("bundleFile"),
        "savedFiles": saved_files,
    }


# For local test
if __name__ == "__main__":
    import os
    import json

    script_dir = os.path.dirname(__file__)
    file_path = os.path.join(script_dir, "sample_event.json")

    with open(file_path) as f:
        event = json.load(f)

    handler(event, None)
