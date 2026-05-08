"""Stable identifiers for vSphere graph nodes."""

from __future__ import annotations

import hashlib
import re
from typing import Any


def slug(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def stable_id(kind: str, *parts: Any) -> str:
    clean = [str(p or "").strip() for p in parts if str(p or "").strip()]
    if clean:
        return ":".join([kind, *clean])
    digest = hashlib.sha1(kind.encode("utf-8")).hexdigest()[:12]
    return f"{kind}:{digest}"


def moid(obj: Any) -> str:
    value = getattr(obj, "_moId", None) or getattr(obj, "moid", None) or getattr(obj, "id", None)
    return str(value or "").strip()

