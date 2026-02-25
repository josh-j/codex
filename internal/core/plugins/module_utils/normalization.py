"""Reusable normalization helpers for collector/report payloads."""

import json
import re


def result_envelope(payload, failed=False, error="", collected_at="", status=None):
    payload = dict(payload or {})
    payload["status"] = str(status if status is not None else ("QUERY_ERROR" if bool(failed) else "SUCCESS"))
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
    Parse a command result dict (rc/stdout/stderr) and extract the first valid JSON object.
    Supports outputs where JSON is preceded or followed by login banners or shell noise.
    """
    command_result = command_result or {}
    rc = int(command_result.get("rc", 1) or 1)
    stdout = str(command_result.get("stdout", "") or "").strip()
    stderr = str(command_result.get("stderr", "") or "").strip()

    payload = None
    script_valid = False

    if stdout:
        # Find all blocks that look like JSON objects
        # Using a non-greedy but balanced-ish approach: look for {} pairs
        # This is a heuristic; json.loads will do the heavy lifting.
        matches = re.finditer(r"(\{.*\})", stdout, re.DOTALL)
        for match in matches:
            candidate = match.group(1).strip()
            try:
                payload = json.loads(candidate)
                if object_only and not isinstance(payload, dict):
                    continue
                script_valid = rc == 0
                break  # Found the first valid JSON block
            except (json.JSONDecodeError, TypeError):
                continue

    return {
        "rc": rc,
        "stdout": stdout,
        "stderr": stderr,
        "payload": payload,
        "script_valid": script_valid,
    }
