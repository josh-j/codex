"""Reusable normalization helpers for collector/report payloads."""

from typing import Any


def result_envelope(
    payload: dict[str, Any],
    failed: bool = False,
    error: str = "",
    collected_at: str = "",
    status: str | None = None,
) -> dict[str, Any]:
    payload = dict(payload or {})
    payload["status"] = str(
        status if status is not None else ("QUERY_ERROR" if bool(failed) else "SUCCESS")
    )
    payload["error"] = str(error or "")
    payload["collected_at"] = str(collected_at or "")
    return payload


def section_defaults(collected_at: str = "") -> dict[str, Any]:
    return {
        "status": "NOT_RUN",
        "error": "",
        "collected_at": str(collected_at or ""),
    }


def merge_section_defaults(
    section: dict[str, Any], payload: dict[str, Any], collected_at: str = ""
) -> dict[str, Any]:
    section = dict(section or {})
    payload = dict(payload or {})
    out = dict(section)
    out.update(payload)
    out.setdefault("status", "NOT_RUN")
    out.setdefault("error", "")
    out.setdefault("collected_at", str(collected_at or ""))
    return out
