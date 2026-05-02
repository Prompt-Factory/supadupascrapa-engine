import json
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen


YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"


def request_json(
    endpoint: str,
    params: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    query = urlencode(
        {
            key: value
            for key, value in params.items()
            if value is not None
        }
    )
    url = f"{YOUTUBE_API_BASE_URL}/{endpoint}?{query}"
    try:
        with urlopen(url) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            error_payload = json.loads(body)
        except json.JSONDecodeError:
            error_payload = {"error": {"message": body}}
        return exc.code, error_payload


def fetch_most_popular_page(
    *,
    api_key: str,
    region_code: str,
    max_results: int,
    page_token: str | None = None,
    video_category_id: str | None = None,
) -> tuple[int, dict[str, Any]]:
    return request_json(
        "videos",
        {
            "part": "snippet,statistics,contentDetails,status",
            "chart": "mostPopular",
            "regionCode": region_code,
            "maxResults": max_results,
            "pageToken": page_token,
            "videoCategoryId": video_category_id,
            "key": api_key,
        },
    )


def fetch_channel_snapshots(
    *,
    api_key: str,
    channel_ids: list[str],
) -> tuple[int, dict[str, Any]]:
    unique_channel_ids = list(dict.fromkeys(channel_ids))
    if not unique_channel_ids:
        return 200, {"items": []}
    return request_json(
        "channels",
        {
            "part": "snippet,statistics",
            "id": ",".join(unique_channel_ids),
            "key": api_key,
        },
    )
