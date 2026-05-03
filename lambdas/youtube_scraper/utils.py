import json
import os
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_local_env_if_present() -> None:
    candidate_paths = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[2] / ".env",
    ]
    for env_path in candidate_paths:
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(
                key.strip(),
                value.strip().strip('"').strip("'"),
            )
        return


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def utc_now_iso() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def utc_days_ago_iso(days: int) -> str:
    target = utc_now() - timedelta(days=days)
    return target.isoformat().replace("+00:00", "Z")


def is_running_in_lambda() -> bool:
    return "AWS_LAMBDA_FUNCTION_NAME" in os.environ


def build_run_id(region_code: str, collected_at: str) -> str:
    compact_timestamp = collected_at.replace("-", "").replace(":", "")
    compact_timestamp = compact_timestamp.replace("+00:00", "Z")
    compact_timestamp = compact_timestamp.replace(".", "")
    return f"{compact_timestamp}_{region_code}_{uuid4().hex[:10]}"


def normalize_s3_prefix(prefix: str) -> str:
    normalized = prefix.strip().strip("/")
    return normalized


def build_s3_key(
    *,
    s3_prefix: str,
    region_code: str,
    subdir: str,
    date_partition: str,
    filename: str,
) -> str:
    normalized_prefix = normalize_s3_prefix(s3_prefix)
    parts = [
        normalized_prefix,
        f"region={region_code}",
        subdir,
        f"date={date_partition}",
        filename,
    ]
    return "/".join(part for part in parts if part)


def build_batch_s3_key(
    *,
    s3_prefix: str,
    date_partition: str,
    filename: str,
) -> str:
    normalized_prefix = normalize_s3_prefix(s3_prefix)
    parts = [
        normalized_prefix,
        "batches",
        f"date={date_partition}",
        filename,
    ]
    return "/".join(part for part in parts if part)


def build_s3_uri(bucket: str, key: str) -> str:
    return f"s3://{bucket}/{key}"


def resolve_output_dir(output_dir: str) -> Path:
    output_path = Path(output_dir)
    if output_path.is_absolute():
        return output_path
    return REPO_ROOT / output_path


def build_partitioned_output_path(
    *,
    output_dir: str,
    region_code: str,
    subdir: str,
    date_partition: str,
    filename: str,
) -> Path:
    output_root = resolve_output_dir(output_dir)
    return (
        output_root
        / f"region={region_code}"
        / subdir
        / f"date={date_partition}"
        / filename
    )


def build_batch_output_path(
    *,
    output_dir: str,
    date_partition: str,
    filename: str,
) -> Path:
    output_root = resolve_output_dir(output_dir)
    return output_root / "batches" / f"date={date_partition}" / filename


class JsonlOutputWriter:
    def __init__(
        self,
        *,
        output_dir: str,
        region_code: str,
        run_id: str,
        collected_at: str,
    ) -> None:
        date_partition = collected_at[:10]
        self.paths = {
            "chart_hits": build_partitioned_output_path(
                output_dir=output_dir,
                region_code=region_code,
                subdir="chart_hits",
                date_partition=date_partition,
                filename=f"{run_id}.jsonl",
            ),
            "search_hits": build_partitioned_output_path(
                output_dir=output_dir,
                region_code=region_code,
                subdir="search_hits",
                date_partition=date_partition,
                filename=f"{run_id}.jsonl",
            ),
            "video_snapshots": build_partitioned_output_path(
                output_dir=output_dir,
                region_code=region_code,
                subdir="video_snapshots",
                date_partition=date_partition,
                filename=f"{run_id}.jsonl",
            ),
            "channel_snapshots": build_partitioned_output_path(
                output_dir=output_dir,
                region_code=region_code,
                subdir="channel_snapshots",
                date_partition=date_partition,
                filename=f"{run_id}.jsonl",
            ),
            "bundle": build_partitioned_output_path(
                output_dir=output_dir,
                region_code=region_code,
                subdir="runs",
                date_partition=date_partition,
                filename=f"{run_id}.json",
            ),
        }
        self._handles: dict[str, TextIO] = {}

    def _get_handle(self, stream_name: str) -> TextIO:
        handle = self._handles.get(stream_name)
        if handle:
            return handle
        path = self.paths[stream_name]
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a", encoding="utf-8")
        self._handles[stream_name] = handle
        return handle

    def write_jsonl_records(
        self,
        stream_name: str,
        records: list[dict[str, Any]],
    ) -> None:
        if not records:
            return
        handle = self._get_handle(stream_name)
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()

    def write_bundle(self, payload: dict[str, Any]) -> str:
        path = self.paths["bundle"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(path)

    def close(self) -> None:
        for handle in self._handles.values():
            handle.close()
        self._handles.clear()

    def build_saved_files_payload(
        self,
        *,
        include_bundle: bool,
    ) -> dict[str, str]:
        saved_files = {
            "chartHitsFile": str(self.paths["chart_hits"]),
            "searchHitsFile": str(self.paths["search_hits"]),
            "videoSnapshotsFile": str(self.paths["video_snapshots"]),
            "channelSnapshotsFile": str(self.paths["channel_snapshots"]),
        }
        if include_bundle:
            saved_files["bundleFile"] = str(self.paths["bundle"])
        return saved_files


class S3JsonlOutputWriter:
    def __init__(
        self,
        *,
        region_code: str,
        run_id: str,
        collected_at: str,
        s3_bucket: str,
        s3_prefix: str,
    ) -> None:
        try:
            import boto3
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "boto3 is required for S3 output in Lambda"
            ) from exc

        date_partition = collected_at[:10]
        self.s3_bucket = s3_bucket
        self.s3_prefix = s3_prefix
        self._s3_client = boto3.client("s3")
        self._temp_root = Path(
            tempfile.mkdtemp(prefix="youtube_scraper_", dir="/tmp")
        )
        self._handles: dict[str, TextIO] = {}
        self.local_paths = {
            "chart_hits": self._temp_root / "chart_hits.jsonl",
            "search_hits": self._temp_root / "search_hits.jsonl",
            "video_snapshots": self._temp_root / "video_snapshots.jsonl",
            "channel_snapshots": (
                self._temp_root / "channel_snapshots.jsonl"
            ),
            "bundle": self._temp_root / "bundle.json",
        }
        self.s3_keys = {
            "chart_hits": build_s3_key(
                s3_prefix=s3_prefix,
                region_code=region_code,
                subdir="chart_hits",
                date_partition=date_partition,
                filename=f"{run_id}.jsonl",
            ),
            "search_hits": build_s3_key(
                s3_prefix=s3_prefix,
                region_code=region_code,
                subdir="search_hits",
                date_partition=date_partition,
                filename=f"{run_id}.jsonl",
            ),
            "video_snapshots": build_s3_key(
                s3_prefix=s3_prefix,
                region_code=region_code,
                subdir="video_snapshots",
                date_partition=date_partition,
                filename=f"{run_id}.jsonl",
            ),
            "channel_snapshots": build_s3_key(
                s3_prefix=s3_prefix,
                region_code=region_code,
                subdir="channel_snapshots",
                date_partition=date_partition,
                filename=f"{run_id}.jsonl",
            ),
            "bundle": build_s3_key(
                s3_prefix=s3_prefix,
                region_code=region_code,
                subdir="runs",
                date_partition=date_partition,
                filename=f"{run_id}.json",
            ),
        }

    def _get_handle(self, stream_name: str) -> TextIO:
        handle = self._handles.get(stream_name)
        if handle:
            return handle
        path = self.local_paths[stream_name]
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a", encoding="utf-8")
        self._handles[stream_name] = handle
        return handle

    def write_jsonl_records(
        self,
        stream_name: str,
        records: list[dict[str, Any]],
    ) -> None:
        if not records:
            return
        handle = self._get_handle(stream_name)
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()

    def write_bundle(self, payload: dict[str, Any]) -> str:
        path = self.local_paths["bundle"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return build_s3_uri(self.s3_bucket, self.s3_keys["bundle"])

    def close(self) -> None:
        try:
            for handle in self._handles.values():
                handle.close()
            self._handles.clear()
            for stream_name, local_path in self.local_paths.items():
                if not local_path.exists():
                    continue
                self._s3_client.upload_file(
                    str(local_path),
                    self.s3_bucket,
                    self.s3_keys[stream_name],
                )
        finally:
            shutil.rmtree(self._temp_root, ignore_errors=True)

    def build_saved_files_payload(
        self,
        *,
        include_bundle: bool,
    ) -> dict[str, str]:
        saved_files = {
            "chartHitsFile": build_s3_uri(
                self.s3_bucket,
                self.s3_keys["chart_hits"],
            ),
            "searchHitsFile": build_s3_uri(
                self.s3_bucket,
                self.s3_keys["search_hits"],
            ),
            "videoSnapshotsFile": build_s3_uri(
                self.s3_bucket,
                self.s3_keys["video_snapshots"],
            ),
            "channelSnapshotsFile": build_s3_uri(
                self.s3_bucket,
                self.s3_keys["channel_snapshots"],
            ),
        }
        if include_bundle:
            saved_files["bundleFile"] = build_s3_uri(
                self.s3_bucket,
                self.s3_keys["bundle"],
            )
        return saved_files


def create_output_writer(
    *,
    output_storage: str,
    output_dir: str,
    region_code: str,
    run_id: str,
    collected_at: str,
    s3_bucket: str | None,
    s3_prefix: str,
) -> JsonlOutputWriter | S3JsonlOutputWriter:
    if output_storage == "s3":
        if not s3_bucket:
            raise ValueError("OUTPUT_S3_BUCKET is required for S3 output")
        return S3JsonlOutputWriter(
            region_code=region_code,
            run_id=run_id,
            collected_at=collected_at,
            s3_bucket=s3_bucket,
            s3_prefix=s3_prefix,
        )
    if output_storage == "local":
        return JsonlOutputWriter(
            output_dir=output_dir,
            region_code=region_code,
            run_id=run_id,
            collected_at=collected_at,
        )
    raise ValueError(f"Unsupported output storage: {output_storage}")


def write_batch_summary_payload(
    *,
    output_storage: str,
    output_dir: str,
    collected_at: str,
    batch_run_id: str,
    payload: dict[str, Any],
    s3_bucket: str | None,
    s3_prefix: str,
) -> str:
    date_partition = collected_at[:10]
    filename = f"{batch_run_id}.json"
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

    if output_storage == "s3":
        if not s3_bucket:
            raise ValueError("OUTPUT_S3_BUCKET is required for S3 output")
        try:
            import boto3
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "boto3 is required for S3 output in Lambda"
            ) from exc
        key = build_batch_s3_key(
            s3_prefix=s3_prefix,
            date_partition=date_partition,
            filename=filename,
        )
        boto3.client("s3").put_object(
            Bucket=s3_bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
        )
        return build_s3_uri(s3_bucket, key)

    path = build_batch_output_path(
        output_dir=output_dir,
        date_partition=date_partition,
        filename=filename,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return str(path)


def build_chart_hit_records(
    *,
    items: list[dict[str, Any]],
    region_code: str,
    collected_at: str,
    run_id: str,
    chart_scope: str,
    requested_video_category_id: str | None,
    requested_video_category_label: str | None,
    page_number: int,
    max_results: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        snippet = item.get("snippet", {})
        rank = ((page_number - 1) * max_results) + index
        records.append(
            {
                "collected_at": collected_at,
                "region": region_code,
                "chart_scope": chart_scope,
                "video_category_id": requested_video_category_id,
                "video_category_label": requested_video_category_label,
                "actual_video_category_id": snippet.get("categoryId"),
                "page": page_number,
                "rank": rank,
                "video_id": item.get("id"),
                "channel_id": snippet.get("channelId"),
                "chart_batch_key": run_id,
                "source": "youtube.videos.list.mostPopular",
            }
        )
    return records


def build_search_hit_records(
    *,
    items: list[dict[str, Any]],
    region_code: str,
    collected_at: str,
    run_id: str,
    search_seed_code: str,
    search_seed_group: str,
    search_seed_label: str,
    query_language: str,
    source_query: str,
    search_order: str,
    published_after: str | None,
    page_number: int,
    max_results: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        snippet = item.get("snippet", {})
        item_id = item.get("id", {})
        rank = ((page_number - 1) * max_results) + index
        records.append(
            {
                "collected_at": collected_at,
                "region": region_code,
                "search_seed_code": search_seed_code,
                "search_seed_group": search_seed_group,
                "search_seed_label": search_seed_label,
                "query_language": query_language,
                "source_query": source_query,
                "search_order": search_order,
                "published_after": published_after,
                "page": page_number,
                "rank": rank,
                "video_id": item_id.get("videoId"),
                "channel_id": snippet.get("channelId"),
                "search_batch_key": run_id,
                "source": "youtube.search.list",
            }
        )
    return records


def build_video_snapshot_records(
    *,
    items: list[dict[str, Any]],
    region_code: str,
    collected_at: str,
    run_id: str,
    chart_scope: str,
    requested_video_category_id: str | None,
    requested_video_category_label: str | None,
    page_number: int,
    max_results: int,
    source: str = "youtube.videos.list.mostPopular",
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        content_details = item.get("contentDetails", {})
        status = item.get("status", {})
        rank = ((page_number - 1) * max_results) + index
        records.append(
            {
                "video_id": item.get("id"),
                "channel_id": snippet.get("channelId"),
                "channel_title": snippet.get("channelTitle"),
                "region": region_code,
                "collected_at": collected_at,
                "chart_scope": chart_scope,
                "video_category_id": snippet.get("categoryId"),
                "requested_video_category_id": requested_video_category_id,
                "requested_video_category_label": (
                    requested_video_category_label
                ),
                "page": page_number,
                "rank": rank,
                "title": snippet.get("title"),
                "description": snippet.get("description"),
                "tags": snippet.get("tags", []),
                "published_at": snippet.get("publishedAt"),
                "duration": content_details.get("duration"),
                "definition": content_details.get("definition"),
                "caption": content_details.get("caption"),
                "made_for_kids": status.get("madeForKids"),
                "view_count": statistics.get("viewCount"),
                "like_count": statistics.get("likeCount"),
                "comment_count": statistics.get("commentCount"),
                "chart_batch_key": run_id,
                "source": source,
            }
        )
    return records


def build_channel_snapshot_records(
    *,
    items: list[dict[str, Any]],
    region_code: str,
    collected_at: str,
    run_id: str,
    chart_scope: str,
    requested_video_category_id: str | None,
    requested_video_category_label: str | None,
    page_number: int,
    source: str = "youtube.channels.list",
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in items:
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        records.append(
            {
                "channel_id": item.get("id"),
                "region": region_code,
                "collected_at": collected_at,
                "chart_scope": chart_scope,
                "requested_video_category_id": requested_video_category_id,
                "requested_video_category_label": (
                    requested_video_category_label
                ),
                "page": page_number,
                "channel_title": snippet.get("title"),
                "channel_view_count": statistics.get("viewCount"),
                "subscriber_count": statistics.get("subscriberCount"),
                "hidden_subscriber_count": statistics.get(
                    "hiddenSubscriberCount"
                ),
                "video_count": statistics.get("videoCount"),
                "chart_batch_key": run_id,
                "source": source,
            }
        )
    return records
