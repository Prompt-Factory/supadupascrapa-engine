from datetime import datetime, timedelta, timezone
from typing import Any

import requests


YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def build_published_after(lookback_days: int) -> str:
    return (
        (datetime.now(timezone.utc) - timedelta(days=lookback_days))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def normalize_search_item(
    item: dict[str, Any],
    *,
    query: str,
    region_code: str,
    order: str,
    published_after: str,
    collected_at: str,
    page: int,
    rank: int,
) -> dict[str, Any]:
    snippet = item.get("snippet", {})
    item_id = item.get("id", {})

    return {
        "query": query,
        "regionCode": region_code,
        "searchOrder": order,
        "publishedAfter": published_after,
        "collectedAt": collected_at,
        "page": page,
        "rank": rank,
        "videoId": item_id.get("videoId"),
        "channelId": snippet.get("channelId"),
        "channelTitle": snippet.get("channelTitle"),
        "title": snippet.get("title"),
        "description": snippet.get("description"),
        "publishedAt": snippet.get("publishedAt"),
        "publishTime": snippet.get("publishTime"),
        "liveBroadcastContent": snippet.get("liveBroadcastContent"),
        "thumbnails": snippet.get("thumbnails", {}),
    }


def parse_count(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def unique_values(values: list[str | None]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def chunk_values(values: list[str], chunk_size: int = 50) -> list[list[str]]:
    return [
        values[index : index + chunk_size]
        for index in range(0, len(values), chunk_size)
    ]


def normalize_video_snapshot(
    item: dict[str, Any],
    *,
    query: str,
    region_code: str,
    industry: str | None,
    category: str | None,
    order: str,
    published_after: str,
    collected_at: str,
) -> dict[str, Any]:
    snippet = item.get("snippet", {})
    statistics = item.get("statistics", {})
    content_details = item.get("contentDetails", {})
    status = item.get("status", {})

    return {
        "videoId": item.get("id"),
        "channelId": snippet.get("channelId"),
        "collectedAt": collected_at,
        "regionCode": region_code,
        "industry": industry,
        "category": category,
        "sourceQuery": query,
        "searchOrder": order,
        "publishedAfter": published_after,
        "title": snippet.get("title"),
        "description": snippet.get("description"),
        "tags": snippet.get("tags", []),
        "publishedAt": snippet.get("publishedAt"),
        "categoryId": snippet.get("categoryId"),
        "defaultLanguage": snippet.get("defaultLanguage"),
        "duration": content_details.get("duration"),
        "caption": content_details.get("caption"),
        "definition": content_details.get("definition"),
        "madeForKids": status.get("madeForKids"),
        "viewCount": parse_count(statistics.get("viewCount")),
        "likeCount": parse_count(statistics.get("likeCount")),
        "commentCount": parse_count(statistics.get("commentCount")),
    }


def normalize_channel_snapshot(
    item: dict[str, Any],
    *,
    query: str,
    region_code: str,
    industry: str | None,
    category: str | None,
    order: str,
    published_after: str,
    collected_at: str,
) -> dict[str, Any]:
    snippet = item.get("snippet", {})
    statistics = item.get("statistics", {})

    return {
        "channelId": item.get("id"),
        "collectedAt": collected_at,
        "regionCode": region_code,
        "industry": industry,
        "category": category,
        "sourceQuery": query,
        "searchOrder": order,
        "publishedAfter": published_after,
        "channelTitle": snippet.get("title"),
        "channelViewCount": parse_count(statistics.get("viewCount")),
        "subscriberCount": parse_count(statistics.get("subscriberCount")),
        "hiddenSubscriberCount": statistics.get(
            "hiddenSubscriberCount"
        ),
        "videoCount": parse_count(statistics.get("videoCount")),
    }


def fetch_video_snapshots(
    *,
    api_key: str,
    video_ids: list[str],
    query: str,
    region_code: str,
    industry: str | None,
    category: str | None,
    order: str,
    published_after: str,
    collected_at: str,
    timeout: int = 30,
) -> tuple[int, dict[str, Any]]:
    unique_video_ids = unique_values(video_ids)
    if not unique_video_ids:
        return 200, {"apiCalls": 0, "items": []}

    snapshots: list[dict[str, Any]] = []
    api_calls = 0

    for video_id_chunk in chunk_values(unique_video_ids):
        response = requests.get(
            YOUTUBE_VIDEOS_URL,
            params={
                "part": "snippet,statistics,contentDetails,status",
                "id": ",".join(video_id_chunk),
                "key": api_key,
            },
            timeout=timeout,
        )
        api_calls += 1
        try:
            response_body = response.json()
        except ValueError:
            response_body = {"rawText": response.text}

        if response.status_code != 200:
            return response.status_code, {
                "apiCalls": api_calls,
                "error": response_body,
            }

        for item in response_body.get("items", []):
            snapshots.append(
                normalize_video_snapshot(
                    item,
                    query=query,
                    region_code=region_code,
                    industry=industry,
                    category=category,
                    order=order,
                    published_after=published_after,
                    collected_at=collected_at,
                )
            )

    return 200, {
        "apiCalls": api_calls,
        "items": snapshots,
    }


def fetch_channel_snapshots(
    *,
    api_key: str,
    channel_ids: list[str],
    query: str,
    region_code: str,
    industry: str | None,
    category: str | None,
    order: str,
    published_after: str,
    collected_at: str,
    timeout: int = 30,
) -> tuple[int, dict[str, Any]]:
    unique_channel_ids = unique_values(channel_ids)
    if not unique_channel_ids:
        return 200, {"apiCalls": 0, "items": []}

    snapshots: list[dict[str, Any]] = []
    api_calls = 0

    for channel_id_chunk in chunk_values(unique_channel_ids):
        response = requests.get(
            YOUTUBE_CHANNELS_URL,
            params={
                "part": "snippet,statistics",
                "id": ",".join(channel_id_chunk),
                "key": api_key,
            },
            timeout=timeout,
        )
        api_calls += 1
        try:
            response_body = response.json()
        except ValueError:
            response_body = {"rawText": response.text}

        if response.status_code != 200:
            return response.status_code, {
                "apiCalls": api_calls,
                "error": response_body,
            }

        for item in response_body.get("items", []):
            snapshots.append(
                normalize_channel_snapshot(
                    item,
                    query=query,
                    region_code=region_code,
                    industry=industry,
                    category=category,
                    order=order,
                    published_after=published_after,
                    collected_at=collected_at,
                )
            )

    return 200, {
        "apiCalls": api_calls,
        "items": snapshots,
    }


def search_discovery(
    *,
    api_key: str,
    query: str,
    region_code: str,
    order: str,
    lookback_days: int,
    max_results: int,
    page_count: int,
    published_after: str | None = None,
    timeout: int = 30,
) -> tuple[int, dict[str, Any]]:
    collected_at = utc_now_iso()
    effective_published_after = published_after or build_published_after(
        lookback_days
    )

    params = {
        "part": "snippet",
        "type": "video",
        "q": query,
        "regionCode": region_code,
        "order": order,
        "publishedAfter": effective_published_after,
        "maxResults": max_results,
        "key": api_key,
    }

    items: list[dict[str, Any]] = []
    page_tokens: list[str] = []
    next_page_token: str | None = None

    for page in range(1, page_count + 1):
        page_params = dict(params)
        if next_page_token:
            page_params["pageToken"] = next_page_token

        response = requests.get(
            YOUTUBE_SEARCH_URL,
            params=page_params,
            timeout=timeout,
        )
        try:
            response_body = response.json()
        except ValueError:
            response_body = {"rawText": response.text}

        if response.status_code != 200:
            return response.status_code, {
                "request": {
                    "query": query,
                    "regionCode": region_code,
                    "order": order,
                    "publishedAfter": effective_published_after,
                    "maxResults": max_results,
                    "pageCount": page_count,
                    "collectedAt": collected_at,
                },
                "summary": {
                    "pagesRequested": page_count,
                    "pagesFetched": page - 1,
                    "itemsFetched": len(items),
                },
                "error": response_body,
            }

        page_items = response_body.get("items", [])
        for page_rank, item in enumerate(page_items, start=1):
            items.append(
                normalize_search_item(
                    item,
                    query=query,
                    region_code=region_code,
                    order=order,
                    published_after=effective_published_after,
                    collected_at=collected_at,
                    page=page,
                    rank=((page - 1) * max_results) + page_rank,
                )
            )

        next_page_token = response_body.get("nextPageToken")
        if next_page_token:
            page_tokens.append(next_page_token)
        else:
            break

    return 200, {
        "request": {
            "query": query,
            "regionCode": region_code,
            "order": order,
            "publishedAfter": effective_published_after,
            "maxResults": max_results,
            "pageCount": page_count,
            "collectedAt": collected_at,
        },
        "summary": {
            "pagesRequested": page_count,
            "pagesFetched": min(page_count, len(page_tokens) + 1),
            "itemsFetched": len(items),
        },
        "pageTokens": page_tokens,
        "items": items,
    }
