import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def is_running_in_lambda() -> bool:
    return "AWS_LAMBDA_FUNCTION_NAME" in os.environ


def resolve_output_dir(output_dir: str) -> Path:
    output_path = Path(output_dir)
    if output_path.is_absolute():
        return output_path
    return Path(__file__).resolve().parents[2] / output_path


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def format_run_timestamp(run_timestamp: str | None = None) -> str:
    if run_timestamp:
        parsed_timestamp = datetime.fromisoformat(
            run_timestamp.replace("Z", "+00:00")
        )
    else:
        parsed_timestamp = datetime.now(timezone.utc)

    return parsed_timestamp.astimezone(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )


def format_run_partition_date(run_timestamp: str | None = None) -> str:
    if run_timestamp:
        parsed_timestamp = datetime.fromisoformat(
            run_timestamp.replace("Z", "+00:00")
        )
    else:
        parsed_timestamp = datetime.now(timezone.utc)

    return parsed_timestamp.astimezone(timezone.utc).strftime(
        "%Y-%m-%d"
    )


def build_run_stem(
    query: str,
    region_code: str,
    *,
    run_timestamp: str | None = None,
) -> str:
    timestamp = format_run_timestamp(run_timestamp)
    query_hash = hashlib.sha1(
        f"{region_code}:{query}".encode("utf-8")
    ).hexdigest()[:10]
    return f"{timestamp}_{region_code}_{query_hash}"


def build_output_path(
    query: str,
    region_code: str,
    output_dir: str,
    *,
    run_timestamp: str | None = None,
    subdir: str | None = None,
    extension: str = "json",
) -> Path:
    resolved_output_dir = resolve_output_dir(output_dir)
    output_path = resolved_output_dir
    if subdir:
        output_path = (
            output_path
            / subdir
            / f"date={format_run_partition_date(run_timestamp)}"
        )

    return output_path / (
        f"{build_run_stem(query, region_code, run_timestamp=run_timestamp)}"
        f".{extension}"
    )


def write_json_file(output_path: Path, payload: Any) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as output_file:
        json.dump(payload, output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")


def write_jsonl_file(output_path: Path, records: list[dict[str, Any]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as output_file:
        for record in records:
            json.dump(record, output_file, ensure_ascii=False)
            output_file.write("\n")


def build_search_hit_records(
    search_items: list[dict[str, Any]],
    *,
    industry: str | None,
    category: str | None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for item in search_items:
        records.append(
            {
                "collected_at": item.get("collectedAt"),
                "region": item.get("regionCode"),
                "industry": industry,
                "category": category,
                "source_query": item.get("query"),
                "search_order": item.get("searchOrder"),
                "published_after": item.get("publishedAfter"),
                "page": item.get("page"),
                "rank": item.get("rank"),
                "video_id": item.get("videoId"),
                "channel_id": item.get("channelId"),
                "channel_title": item.get("channelTitle"),
                "title": item.get("title"),
                "description": item.get("description"),
                "published_at": item.get("publishedAt"),
                "publish_time": item.get("publishTime"),
                "live_broadcast_content": item.get(
                    "liveBroadcastContent"
                ),
                "thumbnails": item.get("thumbnails", {}),
            }
        )

    return records


def build_video_snapshot_records(
    snapshots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for item in snapshots:
        records.append(
            {
                "video_id": item.get("videoId"),
                "channel_id": item.get("channelId"),
                "collected_at": item.get("collectedAt"),
                "region": item.get("regionCode"),
                "industry": item.get("industry"),
                "category": item.get("category"),
                "source_query": item.get("sourceQuery"),
                "search_order": item.get("searchOrder"),
                "published_after": item.get("publishedAfter"),
                "title": item.get("title"),
                "description": item.get("description"),
                "tags": item.get("tags", []),
                "published_at": item.get("publishedAt"),
                "category_id": item.get("categoryId"),
                "default_language": item.get("defaultLanguage"),
                "duration": item.get("duration"),
                "caption": item.get("caption"),
                "definition": item.get("definition"),
                "made_for_kids": item.get("madeForKids"),
                "view_count": item.get("viewCount"),
                "like_count": item.get("likeCount"),
                "comment_count": item.get("commentCount"),
            }
        )

    return records


def build_channel_snapshot_records(
    snapshots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for item in snapshots:
        records.append(
            {
                "channel_id": item.get("channelId"),
                "collected_at": item.get("collectedAt"),
                "channel_title": item.get("channelTitle"),
                "region": item.get("regionCode"),
                "industry": item.get("industry"),
                "category": item.get("category"),
                "source_query": item.get("sourceQuery"),
                "search_order": item.get("searchOrder"),
                "published_after": item.get("publishedAfter"),
                "channel_view_count": item.get("channelViewCount"),
                "subscriber_count": item.get("subscriberCount"),
                "hidden_subscriber_count": item.get(
                    "hiddenSubscriberCount"
                ),
                "video_count": item.get("videoCount"),
            }
        )

    return records


def save_json_output(
    *,
    query: str,
    region_code: str,
    status_code: int,
    response_body: Any,
    output_dir: str,
    run_timestamp: str | None = None,
) -> str:
    output_path = build_output_path(
        query,
        region_code,
        output_dir,
        run_timestamp=run_timestamp,
        subdir="runs",
        extension="json",
    )

    payload = {
        "meta": {
            "query": query,
            "regionCode": region_code,
            "statusCode": status_code,
            "savedAt": utc_now_iso(),
            "source": "youtube.search.list",
        },
        "response": response_body,
    }

    write_json_file(output_path, payload)

    return str(output_path)


def save_jsonl_output(
    *,
    query: str,
    region_code: str,
    records: list[dict[str, Any]],
    output_dir: str,
    subdir: str,
    run_timestamp: str | None = None,
) -> str:
    output_path = build_output_path(
        query,
        region_code,
        output_dir,
        run_timestamp=run_timestamp,
        subdir=subdir,
        extension="jsonl",
    )
    write_jsonl_file(output_path, records)
    return str(output_path)
