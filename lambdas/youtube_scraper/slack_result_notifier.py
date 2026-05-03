import json
import os
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo


DEFAULT_SLACK_TIMEZONE = "Asia/Seoul"


def get_slack_notifier_target(
    event: dict[str, Any],
) -> tuple[str | None, str | None]:
    function_name = (
        event.get("slackNotifierFunctionName")
        or os.getenv("SLACK_NOTIFIER_FUNCTION_NAME")
    )
    channel = (
        event.get("slackResultChannel")
        or os.getenv("SLACK_RESULT_CHANNEL")
    )
    if function_name:
        function_name = str(function_name).strip()
    if channel:
        channel = str(channel).strip()
    return function_name or None, channel or None


def should_send_slack_result(event: dict[str, Any]) -> bool:
    configured_value = event.get("notifySlackResult")
    if configured_value is None:
        function_name, channel = get_slack_notifier_target(event)
        return bool(function_name and channel)
    return bool(configured_value)


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _format_count(value: int) -> str:
    return f"{value:,}"


def _parse_utc_timestamp(timestamp: str | None) -> datetime | None:
    if not timestamp:
        return None
    normalized = timestamp.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_report_timestamp(timestamp: str | None) -> str:
    parsed = _parse_utc_timestamp(timestamp)
    if not parsed:
        return "시간 정보 없음"
    kst_time = parsed.astimezone(ZoneInfo(DEFAULT_SLACK_TIMEZONE))
    return kst_time.strftime("%Y-%m-%d %H:%M KST")


def _aggregate_region_video_sources(
    region_result: dict[str, Any],
) -> tuple[int, int]:
    chart_videos = 0
    search_videos = 0
    for scope_summary in region_result.get("scopeSummaries", []):
        scope_videos = _safe_int(scope_summary.get("videoSnapshotCount"))
        if scope_summary.get("chartScope") == "search":
            search_videos += scope_videos
        else:
            chart_videos += scope_videos
    return chart_videos, search_videos


def _build_failed_region_lines(
    batch_response: dict[str, Any],
) -> list[str]:
    lines: list[str] = []
    for region_result in batch_response.get("regionResults", []):
        region_code = (
            region_result.get("regionPlan", {}) or {}
        ).get("code", "UNKNOWN")
        scope_errors = region_result.get("scopeErrors", [])
        if not scope_errors:
            continue
        first_error = scope_errors[0]
        scope_name = first_error.get("chartScope", "unknown")
        if scope_name == "search":
            seed_code = first_error.get("searchSeedCode", "SEARCH")
            source_query = first_error.get("sourceQuery", "")
            scope_name = f"search/{seed_code}"
            if source_query:
                scope_name += f" ({source_query})"
        elif first_error.get("videoCategoryId"):
            scope_name = (
                f"{scope_name}/{first_error.get('videoCategoryId')}"
            )

        error_payload = first_error.get("error", {}) or {}
        error_message = error_payload.get("message")
        if not error_message:
            details = error_payload.get("errors", [])
            if details:
                detail = details[0] or {}
                reason = detail.get("reason")
                detail_message = detail.get("message")
                if reason and detail_message:
                    error_message = f"{reason}: {detail_message}"
                else:
                    error_message = reason or detail_message
        if not error_message:
            error_message = "unknown error"
        lines.append(f"- {region_code}: {scope_name} -> {error_message}")
    return lines


def build_slack_result_message(batch_response: dict[str, Any]) -> str:
    summary = batch_response.get("summary", {}) or {}
    generated_at = batch_response.get("generatedAt")
    report_timestamp = _format_report_timestamp(generated_at)
    batch_summary_file = (
        batch_response.get("savedFiles", {}) or {}
    ).get("batchSummaryFile")

    failed_region_count = _safe_int(summary.get("failedRegionCount"))
    has_scope_errors = any(
        region_result.get("scopeErrors")
        for region_result in batch_response.get("regionResults", [])
    )

    if failed_region_count > 0 or has_scope_errors:
        lines = [
            f"[SupaDupaScrapa] {report_timestamp} 배치 실행 중 실패가 있었습니다.",
            (
                f"- 성공 region: "
                f"{_format_count(_safe_int(summary.get('successfulRegionCount')))} / "
                f"{_format_count(_safe_int(summary.get('regionCount')))}"
            ),
            (
                f"- video_snapshots: "
                f"{_format_count(_safe_int(summary.get('videoSnapshotCount')))}개"
            ),
            (
                f"- channel_snapshots: "
                f"{_format_count(_safe_int(summary.get('channelSnapshotCount')))}개"
            ),
        ]
        failed_lines = _build_failed_region_lines(batch_response)
        if failed_lines:
            lines.append("- 실패 상세:")
            lines.extend(failed_lines)
        if batch_summary_file:
            lines.append(f"- batch summary: {batch_summary_file}")
        return "\n".join(lines)

    lines = [
        (
            f"{report_timestamp} video_snapshots 기준 "
            f"{_format_count(_safe_int(summary.get('videoSnapshotCount')))}개 "
            f"스크래핑 완료"
        ),
        (
            f"- channel_snapshots: "
            f"{_format_count(_safe_int(summary.get('channelSnapshotCount')))}개"
        ),
        (
            f"- chart_hits: "
            f"{_format_count(_safe_int(summary.get('chartHitCount')))}개"
        ),
        (
            f"- search_hits: "
            f"{_format_count(_safe_int(summary.get('searchHitCount')))}개"
        ),
        "",
        "지역별 video_snapshots",
    ]

    sorted_region_results = sorted(
        batch_response.get("regionResults", []),
        key=lambda item: _safe_int(
            (item.get("summary", {}) or {}).get("videoSnapshotCount")
        ),
        reverse=True,
    )
    for region_result in sorted_region_results:
        region_code = (
            region_result.get("regionPlan", {}) or {}
        ).get("code", "UNKNOWN")
        region_summary = region_result.get("summary", {}) or {}
        chart_videos, search_videos = _aggregate_region_video_sources(
            region_result
        )
        lines.append(
            (
                f"- {region_code}: "
                f"{_format_count(_safe_int(region_summary.get('videoSnapshotCount')))} "
                f"( chart {_format_count(chart_videos)}, "
                f"search {_format_count(search_videos)} )"
            )
        )

    if batch_summary_file:
        lines.extend(
            [
                "",
                f"batch summary: {batch_summary_file}",
            ]
        )
    return "\n".join(lines)


def send_slack_result_notification(
    *,
    batch_response: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    function_name, channel = get_slack_notifier_target(event)
    if not function_name or not channel:
        return {
            "ok": False,
            "skipped": True,
            "reason": "missing notifier target",
        }

    try:
        import boto3
    except ModuleNotFoundError:
        return {
            "ok": False,
            "skipped": True,
            "reason": "boto3 is not available",
        }

    message = build_slack_result_message(batch_response)
    client = boto3.client("lambda")
    response = client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(
            {
                "channel": channel,
                "message": message,
            },
            ensure_ascii=False,
        ).encode("utf-8"),
    )
    payload = {}
    response_payload = response.get("Payload")
    if response_payload is not None:
        raw_body = response_payload.read().decode("utf-8")
        if raw_body:
            try:
                payload = json.loads(raw_body)
            except json.JSONDecodeError:
                payload = {"raw": raw_body}

    return {
        "ok": response.get("StatusCode") == 200,
        "functionName": function_name,
        "channel": channel,
        "statusCode": response.get("StatusCode"),
        "functionError": response.get("FunctionError"),
        "payload": payload,
    }
