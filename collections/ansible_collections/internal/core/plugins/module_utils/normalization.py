"""Reusable normalization helpers for collector/report payloads."""

import json
import re


def result_envelope(payload, failed=False, error="", collected_at="", status=None):
    payload = dict(payload or {})
    payload["status"] = str(
        status if status is not None else ("QUERY_ERROR" if bool(failed) else "SUCCESS")
    )
    payload["error"] = str(error or "")
    payload["collected_at"] = str(collected_at or "")
    return payload


def section_defaults(collected_at=""):
    return {
        "status": "NOT_RUN",
        "error": "",
        "collected_at": str(collected_at or ""),
    }


def merge_section_defaults(section, payload, collected_at=""):
    section = dict(section or {})
    payload = dict(payload or {})
    out = dict(section)
    out.update(payload)
    out.setdefault("status", "NOT_RUN")
    out.setdefault("error", "")
    out.setdefault("collected_at", str(collected_at or ""))
    return out


def parse_json_command_result(command_result, object_only=True):
    """
    Parse a command result dict (rc/stdout/stderr) and extract the first JSON object from stdout.

    Returns a dict with rc/stdout/stderr/payload/script_valid.
    """
    command_result = command_result or {}
    rc = int(command_result.get("rc", 1) or 1)
    stdout = str(command_result.get("stdout", "") or "").strip()
    stderr = str(command_result.get("stderr", "") or "").strip()

    match = re.search(r"(?s)\{.*\}", stdout or "")
    json_text = match.group(0).strip() if match else ""
    script_valid = rc == 0 and len(json_text) > 0
    if object_only:
        script_valid = script_valid and json_text.lstrip().startswith("{")

    if script_valid:
        try:
            payload = json.loads(json_text)
        except Exception:
            payload = None
            script_valid = False
    else:
        payload = None

    return {
        "rc": rc,
        "stdout": stdout,
        "stderr": stderr,
        "payload": payload,
        "script_valid": script_valid,
    }
