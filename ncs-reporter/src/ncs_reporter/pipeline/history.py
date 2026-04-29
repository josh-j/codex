"""History archive helpers for static tree reports."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .._report_context import get_jinja_env

HISTORY_DIR = "history"


def _format_stamp_label(stamp: str) -> str:
    """``20260101`` -> ``2026-01-01``. Anything else passes through unchanged."""
    if len(stamp) == 8 and stamp.isdigit():
        return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
    return stamp


def _read_archive_stamp_manifests(r_root: Path) -> list[dict[str, Any]]:
    """Return ``{stamp, label, paths, rendered_at}`` per archive, newest-first."""
    history_dir = r_root / HISTORY_DIR
    if not history_dir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for stamp_dir in sorted([p for p in history_dir.iterdir() if p.is_dir()], reverse=True):
        try:
            data = json.loads((stamp_dir / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        stamp = str(data.get("stamp") or stamp_dir.name)
        out.append({
            "stamp": stamp,
            "label": _format_stamp_label(stamp),
            "paths": list(data.get("paths") or ()),
            "rendered_at": str(data.get("rendered_at") or ""),
        })
    return out


def _write_stamp_manifest(target_dir: Path, stamp: str, paths: list[str]) -> None:
    """Persist ``manifest.json`` for an archived stamp."""
    target_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "stamp": stamp,
        "rendered_at": datetime.now().isoformat(timespec="seconds"),
        "paths": sorted(set(paths)),
    }
    (target_dir / "manifest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8",
    )


def _history_items_for_path(
    *,
    html_path: str,
    stamps: list[dict[str, Any]],
    current_stamp_prefix: str,
    back_to_root: str,
) -> list[dict[str, Any]]:
    """Build History dropdown items for *html_path*."""
    if not stamps:
        return []

    def _build(label: str, target_prefix: str, paths: set[str]) -> dict[str, Any]:
        is_active = target_prefix == current_stamp_prefix
        if html_path in paths:
            return {
                "text": label,
                "href": "#" if is_active else back_to_root + target_prefix + html_path,
                "active": is_active,
                "css_class": "",
            }
        return {
            "text": label,
            "href": "",
            "active": is_active,
            "css_class": "diverged",
            "tooltip": "Not rendered in this snapshot",
        }

    items: list[dict[str, Any]] = []
    latest = next((s for s in stamps if s.get("is_latest")), None)
    if latest is not None:
        items.append(_build("Latest", "", set(latest.get("paths") or ())))
    for entry in stamps:
        if entry.get("is_latest"):
            continue
        label = entry.get("label") or entry.get("stamp") or ""
        target_prefix = f"{HISTORY_DIR}/{entry['stamp']}/"
        items.append(_build(label, target_prefix, set(entry.get("paths") or ())))
    return items


# Pattern matches a History sub-group emitted by ``_breadcrumb_bar.html.j2``.
_HISTORY_GROUP_RE = re.compile(
    r'<div class="dropdown-group" data-history-path="([^"]+)">History</div>'
    r'(?:[\s\S]*?)</div>',
)


def _patch_history_groups_in_html(
    content: str,
    *,
    history_for_render: list[dict[str, Any]],
    stamp_prefix: str,
    back_to_root: str,
) -> str:
    """Rewrite every History sub-group in *content* with fresh items."""
    template = get_jinja_env().get_template("_breadcrumb_bar.html.j2")
    render_item = template.module.dropdown_item  # type: ignore[attr-defined]

    def _replace(match: "re.Match[str]") -> str:
        html_path = match.group(1)
        items = _history_items_for_path(
            html_path=html_path,
            stamps=history_for_render,
            current_stamp_prefix=stamp_prefix,
            back_to_root=back_to_root,
        )
        items_html = "".join(str(render_item(it)) for it in items)
        return (
            f'<div class="dropdown-group" data-history-path="{html_path}">History</div>'
            f"{items_html}</div>"
        )

    return _HISTORY_GROUP_RE.sub(_replace, content)


def _history_for_render_signature(history_for_render: list[dict[str, Any]]) -> str:
    """Stable digest of the stamp set and path set used by History dropdowns."""
    payload = [
        {
            "stamp": e.get("stamp", ""),
            "is_latest": bool(e.get("is_latest")),
            "paths": sorted(set(e.get("paths") or ())),
        }
        for e in history_for_render
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _refresh_archive_history_dropdowns(
    r_root: Path,
    history_for_render: list[dict[str, Any]],
) -> None:
    """Rewrite archived History dropdowns when the stamp set changes."""
    history_dir = r_root / HISTORY_DIR
    if not history_dir.is_dir():
        return
    state_path = history_dir / ".refresh-state.json"
    signature = _history_for_render_signature(history_for_render)
    try:
        prior = json.loads(state_path.read_text(encoding="utf-8")).get("signature")
    except (OSError, json.JSONDecodeError):
        prior = None
    if prior == signature:
        return
    for stamp_dir in [p for p in history_dir.iterdir() if p.is_dir()]:
        stamp_prefix = f"{HISTORY_DIR}/{stamp_dir.name}/"
        for html_file in stamp_dir.rglob("*.html"):
            rel_to_archive = html_file.relative_to(stamp_dir)
            back_to_root = "../" * (len(rel_to_archive.parts) - 1 + stamp_prefix.count("/"))
            content = html_file.read_text(encoding="utf-8")
            new_content = _patch_history_groups_in_html(
                content,
                history_for_render=history_for_render,
                stamp_prefix=stamp_prefix,
                back_to_root=back_to_root,
            )
            if new_content != content:
                html_file.write_text(new_content, encoding="utf-8")
    state_path.write_text(
        json.dumps({"signature": signature}, sort_keys=True), encoding="utf-8",
    )


def _refresh_history_index(
    r_root: Path,
    archive_stamps: list[dict[str, Any]] | None = None,
) -> None:
    """Maintain ``history/index.json`` as newest-first available stamps."""
    history_dir = r_root / HISTORY_DIR
    if not history_dir.is_dir():
        return
    if archive_stamps is None:
        archive_stamps = _read_archive_stamp_manifests(r_root)
    payload = {
        "stamps": [
            {"stamp": e["stamp"], "rendered_at": e.get("rendered_at", "")}
            for e in archive_stamps
        ],
    }
    (history_dir / "index.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8",
    )
