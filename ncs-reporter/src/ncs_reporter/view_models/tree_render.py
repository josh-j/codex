"""Tree-tier rendering: walks a ``ReportNode`` tree and emits HTML per node.

This is the primary inventory page renderer used by the ``all`` command.

The single responsibility of this module: given a populated tree and the
shared Jinja environment, materialize ``<node_path>/<slug>.html`` for every
node. Filename derivation lives in :class:`NodePath` — nothing here knows
about report filenames.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ncs_reporter.models.report_schema import AlertPanelWidget, ReportSchema
from ncs_reporter.models.tree import ReportNode
from ncs_reporter.pipeline.history import _history_items_for_path
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
    or ``script:``; tree nodes don't read Ansible raw-bundle keys. This is
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
    tree_products: list[dict[str, str]] | None = None,
    schemas_by_name: dict[str, ReportSchema] | None = None,
    stamp_prefix: str = "",
    history_stamps: list[dict[str, Any]] | None = None,
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
        descendant_alerts = cached.get("descendant_alerts", [])
    else:
        seed = node.data_source({}) if node.data_source else {}
        if not isinstance(seed, dict):
            seed = {}
        fields, alerts = _eval_fields_and_alerts(schema, seed)
        descendant_alerts = []

    alerts = list(alerts) + list(descendant_alerts)

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

    # Auto-injected children section: merged into the schema's inventory
    # widget when one exists, otherwise prepended as a synthetic widget,
    # so every page with children has exactly one Inventory card.
    if node.children:
        children_section = _build_children_section(node, node_state, schemas_by_name)
        existing_inventory = next(
            (w for w in widgets_rendered if w.get("type") == "inventory"),
            None,
        )
        if existing_inventory is not None:
            existing_inventory.setdefault("sections", []).insert(0, children_section)
        else:
            widgets_rendered.insert(0, {
                "slug": "tree-children",
                "name": "Inventory",
                "type": "inventory",
                "layout": {"width": "full"},
                "cards": [],
                "sections": [children_section],
            })

    rc = ctx or ReportContext()
    crit = sum(1 for a in alerts if a.get("severity") == "CRITICAL")
    warn = sum(1 for a in alerts if a.get("severity") == "WARNING")
    info = sum(1 for a in alerts if a.get("severity") == "INFO")
    health = "CRITICAL" if crit else "WARNING" if warn else "OK"

    available_alerts = _available_alerts_for_schema(schema)

    # ``stamp_prefix`` is "" for the live tree or "history/<stamp>/" for
    # archived pages — its trailing slashes count the extra ``../``s
    # needed to escape back to the report root.
    extra_depth = stamp_prefix.count("/")
    back_to_root = "../" * (len(node.node_path.segments) + extra_depth)
    breadcrumbs: list[dict[str, Any]] = []
    breadcrumbs.append({
        "type": "link",
        "text": "Site Dashboard",
        "href": back_to_root + "site.html",
        "icon": "home",
    })
    # The active product appears once as the dropdown trigger, not also
    # as an ancestor link — skip the tree root in the ancestor walk below.
    root_node = node
    while root_node.parent is not None:
        root_node = root_node.parent
    active_slug = root_node.slug
    active_title = root_node.title or active_slug
    # Per-crumb history items: every node along the path-from-root-to-current
    # gets a History sub-dropdown answering "what did this specific node look
    # like at stamp X?". Crumbs without sibling navigation become dropdowns
    # whose only purpose is to surface history; existing sibling dropdowns
    # gain a History group below their primary items.
    def _history_for(target_html_path: str) -> list[dict[str, Any]]:
        return _history_items_for_path(
            html_path=target_html_path,
            stamps=history_stamps or [],
            current_stamp_prefix=stamp_prefix,
            back_to_root=back_to_root,
        )

    if tree_products:
        active_html_path = root_node.node_path.html_path.as_posix()
        breadcrumbs.append(_dropdown_crumb(
            text=active_title,
            group_label="Products",
            href=back_to_root + f"{active_slug}/{active_slug}.html" if not node.is_root else None,
            items=[
                {
                    "text": p["name"],
                    "href": back_to_root + p["report"],
                    "active": p["slug"] == active_slug,
                    "css_class": "",
                }
                for p in tree_products
            ],
            history_items=_history_for(active_html_path),
            history_path=active_html_path,
        ))
    # Ancestors with siblings → sibling dropdown; otherwise a history-only
    # dropdown so each crumb remains independently selectable across stamps.
    # Tree root is omitted (covered by Select Product above).
    for ancestor in node.ancestors():
        if ancestor is root_node:
            continue
        siblings = (ancestor.parent.children if ancestor.parent else [])
        ancestor_html_path = ancestor.node_path.html_path.as_posix()
        ancestor_history = _history_for(ancestor_html_path)
        if len(siblings) > 1:
            breadcrumbs.append(_dropdown_crumb(
                text=ancestor.title,
                group_label=_tier_label(ancestor.tier) + "s",
                href=_relative_to(ancestor, node),
                items=[_dropdown_item(s, node, active=s is ancestor) for s in siblings],
                history_items=ancestor_history,
                history_path=ancestor_html_path,
            ))
        elif ancestor_history:
            breadcrumbs.append(_dropdown_crumb(
                text=ancestor.title,
                group_label=None,
                href=_relative_to(ancestor, node),
                items=[],
                history_items=ancestor_history,
                history_path=ancestor_html_path,
            ))
        else:
            breadcrumbs.append({
                "type": "link",
                "text": ancestor.title,
                "href": _relative_to(ancestor, node),
            })
    # Current node renders as a peer-navigation dropdown when it has siblings;
    # otherwise as a history-only dropdown (or a plain label when there's no
    # history either).
    if not node.is_root:
        node_siblings = node.parent.children if node.parent else []
        node_html_path = node.node_path.html_path.as_posix()
        node_history = _history_for(node_html_path)
        if len(node_siblings) > 1:
            breadcrumbs.append(_dropdown_crumb(
                text=node.title,
                group_label=_tier_label(node.tier) + "s",
                items=[_dropdown_item(s, node, active=s is node) for s in node_siblings],
                history_items=node_history,
                history_path=node_html_path,
            ))
        elif node_history:
            breadcrumbs.append(_dropdown_crumb(
                text=node.title,
                group_label=None,
                items=[],
                history_items=node_history,
                history_path=node_html_path,
            ))
        else:
            breadcrumbs.append({"type": "label", "text": node.title})

    # Drill-down dropdown for children.
    if node.children:
        child_tiers = sorted({c.tier or "" for c in node.children})
        child_label = (
            _tier_label(child_tiers[0]) + "s"
            if len(child_tiers) == 1 and child_tiers[0]
            else "Children"
        )
        breadcrumbs.append(_dropdown_crumb(
            text="Select " + (child_label[:-1] if child_label.endswith("s") else child_label),
            group_label=child_label,
            scrollable=True,
            items=[_dropdown_item(c, node, active=False) for c in node.children],
        ))

    breadcrumbs.append({"type": "search", "search_root": back_to_root or "./"})

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
        "available_alerts": available_alerts,
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


def _tier_label(tier: str | None, *, plural: bool = False) -> str:
    """Title-cased tier label, e.g. ``esxi_host`` → ``Esxi Host``."""
    label = (tier or "").replace("_", " ").title()
    return f"{label}s" if plural and label else label


def _dropdown_item(target: ReportNode, origin: ReportNode, *, active: bool) -> dict[str, Any]:
    """Anchor a dropdown item at *origin*; ``href`` is ``#`` when target is origin."""
    return {
        "text": target.title or target.slug,
        "href": "#" if target is origin else _relative_to(target, origin),
        "active": active,
        "css_class": "",
    }


def _dropdown_crumb(
    *,
    text: str,
    items: list[dict[str, Any]],
    group_label: str | None,
    href: str | None = None,
    scrollable: bool = False,
    history_items: list[dict[str, Any]] | None = None,
    history_path: str | None = None,
) -> dict[str, Any]:
    """Build a typed dropdown crumb consumed by ``_breadcrumb_bar.html.j2``.

    ``history_path`` is emitted as ``data-history-path`` so the orchestrator's
    post-render patcher can rebuild the History sub-group in archived pages.
    """
    crumb: dict[str, Any] = {
        "type": "dropdown",
        "text": text,
        "group_label": group_label,
        "scrollable": scrollable,
        "items": items,
    }
    if href is not None:
        crumb["href"] = href
    if history_items:
        crumb["history_items"] = history_items
    if history_path is not None:
        crumb["history_path"] = history_path
    return crumb


_AVAILABLE_ALERTS_CACHE: dict[int, tuple[dict[str, Any], ...]] = {}


_JINJA_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)(?:\s*\|[^}]*)?\s*\}\}")


def _describe_alert_template(template: str) -> str:
    """Convert an alert message template into a human-readable description
    for the catalog popover by replacing ``{{ var | filter }}`` with
    ``‹var›`` placeholders. Documentation, not evaluation — never raises."""
    return _JINJA_VAR_RE.sub(lambda m: f"‹{m.group(1)}›", template)


def _available_alerts_for_schema(schema: Any) -> tuple[dict[str, Any], ...]:
    """All alert rules defined on a schema, materialized once per schema
    and shared across every tree node that uses it. Cache is keyed by
    object identity (Pydantic models are unhashable, so an LRU cache
    won't take them; the cache lives only as long as the render pass)."""
    if schema is None or not getattr(schema, "alerts", None):
        return ()
    cached = _AVAILABLE_ALERTS_CACHE.get(id(schema))
    if cached is not None:
        return cached
    rules = tuple(
        {
            "id": rule.id,
            "category": rule.category,
            "severity": rule.severity,
            "message": _describe_alert_template(rule.msg),
            "when": rule.when,
        }
        for rule in schema.alerts
    )
    _AVAILABLE_ALERTS_CACHE[id(schema)] = rules
    return rules


def _attach_alert_rollups(root: ReportNode, state: dict[int, dict[str, Any]]) -> None:
    """Resolve ``_node_ref`` markers on inventory-row dicts into
    ``ncs_alerts`` rollup dicts.

    Rows are kept idempotent across re-renders: ``_node_ref`` stays on
    the row (the first call resolves it; subsequent calls overwrite the
    same ``ncs_alerts`` field with the latest rollup), so a second
    render in the same process gets fresh numbers instead of silently
    inheriting stale ones from the first.
    """
    for node in root.walk():
        if node.data_source is None:
            continue
        seed = node.data_source({})
        if not isinstance(seed, dict):
            continue
        for value in seed.values():
            if not isinstance(value, list):
                continue
            for row in value:
                if not isinstance(row, dict):
                    continue
                ref = row.get("_node_ref")
                if ref is None:
                    continue
                rollup = (state.get(ref) or {}).get("rollup") or {}
                row["ncs_alerts"] = {
                    "info": int(rollup.get("info", 0) or 0),
                    "warning": int(rollup.get("warning", 0) or 0),
                    "critical": int(rollup.get("critical", 0) or 0),
                }


def _children_label_from_spec(
    schemas_by_name: dict[str, ReportSchema] | None,
    child_tier: str,
) -> str | None:
    """Look up the grandchild-column label for *child_tier* by scanning
    every schema's ``tree.levels`` for a level matching the tier and
    returning its declared ``children_label``. Returns ``None`` if
    nothing's declared — the caller falls back to a generic placeholder."""
    if not schemas_by_name or not child_tier:
        return None
    for schema in schemas_by_name.values():
        if schema.tree is None:
            continue
        for level in schema.tree.levels:
            if level.tier == child_tier and level.children_label:
                return level.children_label
    return None


def _build_children_section(
    node: ReportNode,
    node_state: dict[int, dict[str, Any]] | None,
    schemas_by_name: dict[str, ReportSchema] | None = None,
) -> dict[str, Any]:
    """Build the auto children section that lives inside the page's
    Inventory widget. Title reflects the child tier, and the third column
    is named after the *grandchild* tier (e.g. ``VMs`` when children are
    ESXi hosts) — resolved from the spec's ``children_label`` so labels
    are pure config."""
    child_tiers = sorted({c.tier or "" for c in node.children})
    if len(child_tiers) == 1 and child_tiers[0]:
        tier = child_tiers[0]
        tier_label = tier.replace("_", " ").title()
        section_name = tier_label if len(node.children) == 1 else f"{tier_label}s"
    else:
        section_name = "Child" if len(node.children) == 1 else "Children"
        tier = ""
    grandchild_tiers = sorted({gc.tier or "" for child in node.children for gc in child.children})
    if len(grandchild_tiers) == 1 and grandchild_tiers[0]:
        grandchild_label = _tier_label(grandchild_tiers[0], plural=len(node.children) != 1)
    else:
        grandchild_label = _children_label_from_spec(schemas_by_name, tier) or "Sub-nodes"
    columns = [
        {"name": "Name"},
        {"name": grandchild_label},
        {"name": "NCS Alerts"},
    ]
    rows = []
    for child in node.children:
        child_rollup = (node_state or {}).get(id(child), {}).get("rollup", {}) or {}
        crit = int(child_rollup.get("critical", 0) or 0)
        warn = int(child_rollup.get("warning", 0) or 0)
        info = int(child_rollup.get("info", 0) or 0)
        rows.append([
            {
                "value": child.title or child.slug,
                "as": None,
                "link": _relative_to(child, node),
                "css_class": "",
            },
            {"value": len(child.children), "as": None, "link": None, "css_class": ""},
            {
                "value": {"info": info, "warning": warn, "critical": crit},
                "as": "severity-tally",
                "link": None,
                "css_class": "",
            },
        ])
    return {
        "name": section_name,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
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
        node_seed = node.data_source({}) if node.data_source else {}
        if schema is not None and isinstance(node_seed, dict):
            fields, alerts = _eval_fields_and_alerts(schema, node_seed)
        rollup = {"critical": 0, "warning": 0, "info": 0}
        for a in alerts:
            sev = str(a.get("severity", "")).lower()
            if sev in rollup:
                rollup[sev] += 1
        # Per-node descendant_alerts list — a parent's NCS Alerts widget
        # surfaces them with an ``origin`` tag so operators can see which
        # descendant fired without drilling down.
        descendant_alerts: list[dict[str, Any]] = []
        for child in node.children:
            child_state = state.get(id(child), {})
            child_rollup = child_state.get("rollup", {})
            for k in rollup:
                rollup[k] += child_rollup.get(k, 0)
            # Tag each child's own alerts with the child as origin (only
            # once; deeper descendants already carry a deeper origin set
            # from their own state entry).
            for a in child_state.get("alerts", []):
                descendant_alerts.append({**a, "origin": child.title or child.slug})
            descendant_alerts.extend(child_state.get("descendant_alerts", []))
        state[id(node)] = {
            "fields": fields,
            "alerts": alerts,
            "rollup": rollup,
            "descendant_alerts": descendant_alerts,
        }
    return state


def render_tree(
    root: ReportNode,
    *,
    schemas_by_name: dict[str, ReportSchema],
    env: Any,  # jinja2.Environment (kept as Any to avoid hard import coupling)
    output_root: Path,
    ctx: ReportContext | None = None,
    template_name: str = "generic_tree_node.html.j2",
    tree_products: list[dict[str, str]] | None = None,
    stamp_prefix: str = "",
    history_stamps: list[dict[str, Any]] | None = None,
    tree_state: dict[int, dict[str, Any]] | None = None,
) -> list[Path]:
    """Render every node in *root*'s subtree, returning the list of HTML paths written.

    Pass *tree_state* when the caller already computed it (e.g. for a
    parallel archive render of the same tree) to skip the per-node
    schema-evaluation pass.
    """
    tpl = env.get_template(template_name)
    if tree_state is None:
        tree_state = _compute_tree_state(root, schemas_by_name)
        # Resolve ``_node_ref`` rows into rollup dicts after evaluation —
        # only needed once per tree, so we skip when state was reused.
        _attach_alert_rollups(root, tree_state)
    written: list[Path] = []
    for node in root.walk():
        schema = schemas_by_name.get(node.schema_name)
        if schema is None:
            logger.warning("no schema for tree-node %s (tier=%s)", node.slug, node.tier)
            continue
        view = build_tree_node_view(
            node, schema=schema, ctx=ctx, node_state=tree_state, tree_products=tree_products,
            schemas_by_name=schemas_by_name,
            stamp_prefix=stamp_prefix, history_stamps=history_stamps,
        )
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
