"""Tree-tier rendering: walks a ``ReportNode`` tree and emits HTML per node.

Currently this is the *additive* path — the main ``all`` command still runs
the legacy platform/fleet/host render too. Once parity + fixtures land in a
later phase, this becomes the primary renderer and the legacy path is
removed.

The single responsibility of this module: given a populated tree and the
shared Jinja environment, materialize ``<node_path>/<slug>.html`` for every
node. Filename derivation lives in :class:`NodePath` — nothing here knows
about report filenames.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from ncs_reporter.models.report_schema import AlertPanelWidget, ReportSchema
from ncs_reporter.models.tree import ReportNode
from ncs_reporter.normalization._when import eval_compute
from ncs_reporter.normalization.schema_driven import build_schema_alerts, normalize_from_schema

from .._report_context import ReportContext
from .generic import _SEVERITY_ORDER, _render_widget

logger = logging.getLogger(__name__)


def _looks_like_bundle(data: dict[str, Any]) -> bool:
    """True when *data* has a top-level ``raw_<type>`` key with a ``data`` dict envelope."""
    for key, value in data.items():
        if key.startswith("raw_") and isinstance(value, dict) and isinstance(value.get("data"), dict):
            return True
    return False


def _eval_schema_fields(schema: ReportSchema, seed: dict[str, Any]) -> dict[str, Any]:
    """Evaluate *schema.fields* starting from *seed*.

    Tree-tier schemas use ``compute:`` and ``fallback:`` only (no ``path:``
    or ``script:`` — tree nodes don't read Ansible raw-bundle keys). This is
    a simplified variant of :func:`extract_fields` that skips the passes we
    don't need.
    """
    fields: dict[str, Any] = dict(seed)
    for name, spec in schema.fields.items():
        if spec.compute is not None:
            try:
                fields[name] = eval_compute(spec.compute, fields)
            except Exception as exc:  # noqa: BLE001
                logger.warning("tree-node compute field '%s' failed: %s", name, exc)
    return fields




def _eval_fields_and_alerts(
    schema: ReportSchema,
    seed: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return ``(fields, alerts)`` for a node's schema evaluated against *seed*.

    Bundle-shaped seeds (``raw_<type>`` envelopes) go through full
    :func:`normalize_from_schema` so path/compute/script fields resolve; flat
    seeds (tier schemas) use the compute-only fast path.
    """
    if _looks_like_bundle(seed):
        normalized = normalize_from_schema(schema, seed)
        return normalized["fields"], normalized["alerts"]
    fields = _eval_schema_fields(schema, seed)
    return fields, build_schema_alerts(schema, fields)


def build_tree_node_view(
    node: ReportNode,
    *,
    schema: ReportSchema,
    ctx: ReportContext | None = None,
    node_state: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a template context dict for a single tree node.

    The node's ``data_source`` supplies the seed fields dict; the schema's
    ``compute:`` / ``fallback:`` declarations layer on top. Widgets are
    rendered via the existing ``_render_widget`` helper so all widget types
    behave identically on tree-tier pages.

    ``node_state`` is the tree-wide cache populated by
    :func:`_compute_tree_state` — when passed, this function reuses the
    pre-computed fields/alerts/rollup for *node* and its children instead of
    re-evaluating them.
    """
    cached = (node_state or {}).get(id(node))
    if cached is not None:
        fields = cached["fields"]
        alerts = cached["alerts"]
    else:
        seed = node.data_source({}) if node.data_source else {}
        if not isinstance(seed, dict):
            seed = {}
        fields, alerts = _eval_fields_and_alerts(schema, seed)

    alerts.sort(key=lambda a: (
        _SEVERITY_ORDER.get(a.get("severity", "INFO"), 3),
        a.get("category", ""),
        a.get("message", ""),
    ))

    effective_widgets = list(schema.widgets)
    if not any(isinstance(w, AlertPanelWidget) for w in effective_widgets):
        effective_widgets.insert(
            0,
            AlertPanelWidget(slug="active_alerts", name="Active Alerts", type="alert_panel"),
        )

    widgets_rendered: list[dict[str, Any]] = []
    for w in effective_widgets:
        rendered = _render_widget(w, fields, alerts, field_specs=schema.fields)
        if rendered is not None:
            widgets_rendered.append(rendered)

    rc = ctx or ReportContext()
    crit = sum(1 for a in alerts if a.get("severity") == "CRITICAL")
    warn = sum(1 for a in alerts if a.get("severity") == "WARNING")
    info = sum(1 for a in alerts if a.get("severity") == "INFO")
    health = "CRITICAL" if crit else "WARNING" if warn else "OK"

    # Breadcrumb: Site → <ancestors…> → current. Site link is only added
    # when this node isn't the root itself (root pages don't need a self-link).
    breadcrumbs: list[dict[str, Any]] = []
    if not node.is_root:
        # The page's directory has len(node_path.segments) segments below the
        # report root (one per tier, including the "platform/" umbrella), so
        # that many "../" are needed to reach site.html.
        breadcrumbs.append({
            "text": "Site",
            "href": "../" * len(node.node_path.segments) + "site.html",
        })
    for ancestor in node.ancestors():
        breadcrumbs.append({"text": ancestor.title, "href": _relative_to(ancestor, node)})
    breadcrumbs.append({"text": node.title, "href": None})

    return {
        "meta": {
            "tier": node.tier,
            "slug": node.slug,
            "title": node.title,
            "display_name": schema.display_name,
            "report_date": rc.report_date,
            "report_stamp": rc.report_stamp,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        },
        "health": health,
        "summary": {
            "total": len(alerts),
            "critical_count": crit,
            "warning_count": warn,
            "info_count": info,
        },
        "alerts": alerts,
        "widgets": widgets_rendered,
        "nav": {
            "breadcrumbs": breadcrumbs,
            "children": [
                {
                    "title": child.title,
                    "tier": child.tier,
                    "url": _relative_to(child, node),
                    "child_count": len(child.children),
                    "rollup": ((node_state or {}).get(id(child), {}).get("rollup", {"critical": 0, "warning": 0, "info": 0})),
                }
                for child in node.children
            ],
            "descendant_rollup": ((node_state or {}).get(id(node), {}).get("rollup", {"critical": 0, "warning": 0, "info": 0})),
        },
    }


def _relative_to(target: ReportNode, origin: ReportNode) -> str:
    """Relative href from *origin*'s node dir to *target*'s HTML report."""
    origin_parts = list(origin.node_path.segments)
    target_parts = list(target.node_path.segments)
    # Find common prefix
    common = 0
    while common < min(len(origin_parts), len(target_parts)) and origin_parts[common] == target_parts[common]:
        common += 1
    up = ["..", ] * (len(origin_parts) - common)
    down = target_parts[common:]
    rel_dir_segments = up + down
    filename = f"{target.slug}.html"
    if not rel_dir_segments:
        return filename
    return "/".join([*rel_dir_segments, filename])


def _compute_tree_state(
    root: ReportNode,
    schemas_by_name: dict[str, ReportSchema],
) -> dict[int, dict[str, Any]]:
    """Evaluate every node's schema once and accumulate subtree alert counts.

    Returns a dict keyed by ``id(node)`` with entries of shape::

        {"fields": dict, "alerts": list[dict], "rollup": {critical, warning, info}}

    ``fields`` and ``alerts`` are exactly what :func:`build_tree_node_view`
    needs for its render pass, so callers should reuse them rather than
    re-evaluating the schema. ``rollup`` sums this node's own alerts plus
    all descendants' — for the children-nav severity badges on each parent
    page.

    The dict is valid for the *lifetime of this call only*. ``id(node)``
    values are recycled after garbage collection, so the dict must not be
    cached across ``render_tree()`` invocations.
    """
    state: dict[int, dict[str, Any]] = {}
    ordered: list[ReportNode] = list(root.walk())
    ordered.sort(key=lambda n: n.depth, reverse=True)
    for node in ordered:
        schema = schemas_by_name.get(node.schema_name)
        fields: dict[str, Any] = {}
        alerts: list[dict[str, Any]] = []
        if schema is not None:
            seed = node.data_source({}) if node.data_source else {}
            if isinstance(seed, dict):
                fields, alerts = _eval_fields_and_alerts(schema, seed)
        rollup = {"critical": 0, "warning": 0, "info": 0}
        for a in alerts:
            sev = str(a.get("severity", "")).lower()
            if sev in rollup:
                rollup[sev] += 1
        for child in node.children:
            child_rollup = state.get(id(child), {}).get("rollup", {})
            for k in rollup:
                rollup[k] += child_rollup.get(k, 0)
        state[id(node)] = {"fields": fields, "alerts": alerts, "rollup": rollup}
    return state


def render_tree(
    root: ReportNode,
    *,
    schemas_by_name: dict[str, ReportSchema],
    env: Any,  # jinja2.Environment (kept as Any to avoid hard import coupling)
    output_root: Path,
    ctx: ReportContext | None = None,
    template_name: str = "generic_tree_node.html.j2",
) -> list[Path]:
    """Render every node in *root*'s subtree, returning the list of HTML paths written."""
    tpl = env.get_template(template_name)
    tree_state = _compute_tree_state(root, schemas_by_name)
    written: list[Path] = []
    for node in root.walk():
        schema = schemas_by_name.get(node.schema_name)
        if schema is None:
            logger.warning("no schema for tree-node %s (tier=%s)", node.slug, node.tier)
            continue
        view = build_tree_node_view(node, schema=schema, ctx=ctx, node_state=tree_state)
        out_path = node.node_path.resolve_under(output_root) / f"{node.slug}.html"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        content = tpl.render(
            tree_node_view=view,
            report_date=view["meta"]["report_date"],
            report_stamp=view["meta"]["report_stamp"],
        )
        out_path.write_text(content)
        written.append(out_path)
    return written
