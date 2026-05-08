"""Declarative normalization DSL used by schema fields.

The DSL intentionally stays small and data-shaped: it provides generic
object/list/scalar operations that configs can compose instead of embedding
large Python scripts or Jinja programs.

Operator dispatch is registry-driven via ``_OPS``. Adding a new operator
means writing one ``_op_<name>(spec_value, ctx)`` function and registering
it in ``_OPS`` (and adding a JSON-schema fragment in
``_NORMALIZE_OP_SCHEMAS`` for IDE autocomplete).
"""

from __future__ import annotations

import dataclasses
import functools
import logging
import re
from collections.abc import Callable
from typing import Any

from ._fields import resolve_field, traverse
from ._when import _age_days, _compile_template, _lookup, _truthy, eval_compute

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Caches and small helpers
# ---------------------------------------------------------------------------


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {})


@functools.lru_cache(maxsize=512)
def _compiled_re(pattern: str, flags: int) -> re.Pattern[str]:
    return re.compile(pattern, flags)


@functools.lru_cache(maxsize=2048)
def _split_path(path: str) -> tuple[str, ...]:
    """Cache `path.split('.')` — paths come from the (bounded) schema set."""
    return tuple(seg for seg in path.split(".") if seg)


def _coerce_iterable(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [{"key": key, "value": val} for key, val in value.items()]
    return []


# ---------------------------------------------------------------------------
# EvalContext: collapses the (base, item, parent, local) tuple threaded
# through every internal function. ``base`` is the field-set built up by
# prior extract_fields passes; ``item``/``parent``/``local`` track the
# current row, the parent row (for nested for_each/expand), and any
# locally-mapped values (the result_item being constructed in _eval_list).
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class EvalContext:
    base: dict[str, Any]
    item: Any = None
    parent: Any = None
    local: dict[str, Any] | None = None

    def with_item(self, item: Any, parent: Any | None = None) -> EvalContext:
        # Direct construction is ~12× faster than `dataclasses.replace`; this
        # is in the per-row hot path of `_eval_list`.
        return EvalContext(self.base, item, parent, self.local)

    def with_local(self, local: dict[str, Any]) -> EvalContext:
        return EvalContext(self.base, self.item, self.parent, local)

    def merged(self) -> dict[str, Any]:
        """Eager merged-dict view for Jinja/expr/template evaluation.

        Most resolution paths don't need this; build it only when handing
        the context to a template-engine call.
        """
        ctx = dict(self.base)
        if isinstance(self.item, dict):
            ctx.update(self.item)
        if self.local:
            ctx.update(self.local)
        ctx["item"] = self.item
        ctx["parent"] = self.parent
        return ctx


# ---------------------------------------------------------------------------
# Path traversal
# ---------------------------------------------------------------------------


def _path_get(obj: Any, path: str) -> Any:
    return traverse(obj, _split_path(path))


def _resolve_path(path: str, ctx: EvalContext) -> Any:
    if path == "item":
        return ctx.item
    if path.startswith("item."):
        return _path_get(ctx.item, path[5:])
    if path == "parent":
        return ctx.parent
    if path.startswith("parent."):
        return _path_get(ctx.parent, path[7:])
    head = path.split(".", 1)[0]
    if ctx.local and head in ctx.local:
        return _path_get(ctx.local, path)
    if isinstance(ctx.item, dict) and head in ctx.item:
        return _path_get(ctx.item, path)
    # Fall back to the broader Jinja-aware resolver — only this branch
    # needs the merged context, so defer the dict copy until now.
    return resolve_field(path, ctx.merged())


def _flatten_path(path: str, ctx: EvalContext) -> list[Any]:
    # Most flatten: paths target a top-level bundle key (`raw.X[]…`) and
    # never need the merged dict — defer building it until we know we
    # can't satisfy the head segment from `item`/`parent`/`base`.
    if path.startswith("item."):
        roots: list[Any] = [ctx.item]
        path = path[5:]
    elif path == "item":
        return ctx.item if isinstance(ctx.item, list) else [ctx.item]
    elif path.startswith("parent."):
        roots = [ctx.parent]
        path = path[7:]
    elif path == "parent":
        return ctx.parent if isinstance(ctx.parent, list) else [ctx.parent]
    else:
        head = path.split(".", 1)[0].rstrip("[]")
        if head and head in ctx.base:
            roots = [ctx.base]
        else:
            roots = [ctx.merged()]

    for raw_segment in path.split("."):
        if not raw_segment:
            continue
        expand = raw_segment.endswith("[]")
        segment = raw_segment[:-2] if expand else raw_segment
        next_roots: list[Any] = []
        for root in roots:
            value = _path_get(root, segment) if segment else root
            if expand:
                if isinstance(value, list):
                    next_roots.extend(value)
                elif value is not None:
                    next_roots.append(value)
            else:
                next_roots.append(value)
        roots = [r for r in next_roots if r is not None]
    return roots


# ---------------------------------------------------------------------------
# Predicates (`include_where:` / `exclude_where:` / `find.where:`)
# ---------------------------------------------------------------------------


_COMPARE_OPS: dict[str, Any] = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a is not None and b is not None and a > b,
    "ge": lambda a, b: a is not None and b is not None and a >= b,
    "lt": lambda a, b: a is not None and b is not None and a < b,
    "le": lambda a, b: a is not None and b is not None and a <= b,
    "in": lambda a, b: isinstance(b, (list, tuple, set, str)) and a in b,
    "not_in": lambda a, b: not (isinstance(b, (list, tuple, set, str)) and a in b),
    "contains": lambda a, b: isinstance(a, (list, tuple, set, str)) and b in a,
    "matches": lambda a, b: bool(_compiled_re(str(b), re.IGNORECASE).search("" if a is None else str(a))),
}


def _resolve_predicate_operand(spec: Any, ctx: EvalContext) -> Any:
    """Resolve a predicate field/value: dicts go through _eval_value, scalars stay literal."""
    if isinstance(spec, dict):
        return _eval_value(spec, ctx)
    return spec


def _eval_predicate(predicate: Any, ctx: EvalContext) -> bool:
    if not isinstance(predicate, dict):
        return False

    if "any" in predicate:
        return any(_eval_predicate(p, ctx) for p in predicate["any"])
    if "all" in predicate:
        return all(_eval_predicate(p, ctx) for p in predicate["all"])
    if "not" in predicate:
        return not _eval_predicate(predicate["not"], ctx)
    if "defined" in predicate:
        target = predicate["defined"]
        if isinstance(target, str):
            value = _resolve_path(target, ctx)
        else:
            value = _resolve_predicate_operand(target, ctx)
        return value is not None

    if "op" in predicate:
        op = str(predicate["op"])
        compare = _COMPARE_OPS.get(op)
        if compare is None:
            return False
        field_spec = predicate.get("field", "item")
        if isinstance(field_spec, str):
            left = _resolve_path(field_spec, ctx)
        else:
            left = _resolve_predicate_operand(field_spec, ctx)
        right = _resolve_predicate_operand(predicate.get("value"), ctx)
        return bool(compare(left, right))

    for key, expected in predicate.items():
        actual = _resolve_path(key, ctx)
        if isinstance(expected, dict) and ("op" in expected or any(k in expected for k in _COMPARE_OPS)):
            if "op" in expected:
                sub = {"field": key, **expected}
            else:
                op_key, op_value = next(iter(expected.items()))
                sub = {"field": key, "op": op_key, "value": op_value}
            if not _eval_predicate(sub, ctx):
                return False
            continue
        expected_value = _resolve_predicate_operand(expected, ctx)
        if actual != expected_value:
            return False
    return True


def _eval_predicate_list(spec: Any, ctx: EvalContext) -> bool:
    """A predicate may be a single dict (AND of clauses) or a list (still AND)."""
    if spec is None:
        return True
    if isinstance(spec, list):
        return all(_eval_predicate(p, ctx) for p in spec)
    return _eval_predicate(spec, ctx)


# ---------------------------------------------------------------------------
# `list:` operator (the heaviest handler — kept as its own function for
# legibility; the registry below points to `_op_list` which forwards here).
# ---------------------------------------------------------------------------


def _eval_list(spec: dict[str, Any], ctx: EvalContext) -> list[Any]:
    if "for_each" in spec:
        parents = _coerce_iterable(_eval_value(spec["for_each"], ctx))
        source_items: list[tuple[Any, Any]] = []
        expand = spec.get("expand")
        for parent_item in parents:
            children: Any
            if expand:
                children = _resolve_path(str(expand), ctx.with_item(parent_item, ctx.parent))
            else:
                children = [parent_item]
            children = _coerce_iterable(children) if not isinstance(children, list) else children
            source_items.extend((child, parent_item) for child in children)
    else:
        source_spec = spec.get("source", [])
        source = _eval_value(source_spec, ctx)
        source_list = _coerce_iterable(source) if not isinstance(source, list) else source
        source_items = [(source_item, ctx.parent) for source_item in source_list]

    exclude_regex = spec.get("exclude_match_any")
    include_where = spec.get("include_where")
    exclude_where = spec.get("exclude_where")
    include_source = bool(spec.get("include_source", True))
    mapped = spec.get("map")
    out: list[Any] = []
    for source_item, parent_item in source_items:
        row_ctx = ctx.with_item(source_item, parent_item)
        if isinstance(exclude_regex, dict):
            field_value = _resolve_path(str(exclude_regex.get("field", "item")), row_ctx)
            patterns = _eval_value(exclude_regex.get("patterns", []), row_ctx)
            if not isinstance(patterns, list):
                patterns = [patterns] if patterns else []
            if any(pattern and _compiled_re(str(pattern), re.IGNORECASE).search(str(field_value)) for pattern in patterns):
                continue

        if include_where is not None and not _eval_predicate_list(include_where, row_ctx):
            continue
        if exclude_where is not None and _eval_predicate_list(exclude_where, row_ctx):
            continue

        if not isinstance(mapped, dict):
            out.append(source_item)
            continue

        if include_source and isinstance(source_item, dict):
            result_item: dict[str, Any] = dict(source_item)
        else:
            result_item = {}
        local_ctx = row_ctx.with_local(result_item)
        for key, value_spec in mapped.items():
            result_item[key] = _eval_value(value_spec, local_ctx)
        out.append(result_item)
    return out


# ---------------------------------------------------------------------------
# Operator handlers
#
# `_op_X(value, ctx)` receives the right-hand side of the operator key
# (e.g. `{count: items}` → `value="items"`). Multi-key ops (`first_of`,
# `if`) live in `_MULTI_KEY_OPS` below and receive the full spec dict.
# ---------------------------------------------------------------------------


def _op_const(value: Any, ctx: EvalContext) -> Any:
    return value


def _op_path(value: Any, ctx: EvalContext) -> Any:
    return _resolve_path(str(value), ctx)


def _op_flatten(value: Any, ctx: EvalContext) -> Any:
    return _flatten_path(str(value), ctx)


def _op_template(value: Any, ctx: EvalContext) -> Any:
    return _compile_template(str(value)).render(**ctx.merged())


def _op_expr(value: Any, ctx: EvalContext) -> Any:
    return eval_compute(str(value), ctx.merged())


def _op_object(value: Any, ctx: EvalContext) -> Any:
    return {k: _eval_value(v, ctx) for k, v in value.items()}


def _op_list(value: Any, ctx: EvalContext) -> Any:
    return _eval_list(value, ctx)


def _op_count(value: Any, ctx: EvalContext) -> Any:
    resolved = _eval_value(value, ctx)
    return len(resolved) if isinstance(resolved, (list, dict, str)) else 0


def _op_pluck(value: Any, ctx: EvalContext) -> Any:
    raw_source = _eval_value(value.get("source", []), ctx)
    source = _coerce_iterable(raw_source) if not isinstance(raw_source, list) else raw_source
    path = str(value.get("path", "item"))
    return [_resolve_path(path, ctx.with_item(row, ctx.parent)) for row in source]


def _op_truthy(value: Any, ctx: EvalContext) -> Any:
    return _truthy(_eval_value(value, ctx))


def _op_lookup(value: Any, ctx: EvalContext) -> Any:
    return _lookup(_eval_value(value.get("value"), ctx), value.get("map", {}), value.get("default"))


def _op_regex_search(value: Any, ctx: EvalContext) -> Any:
    text = _eval_value(value.get("value"), ctx)
    pattern = str(value.get("pattern", ""))
    flags = re.IGNORECASE if value.get("ignorecase") else 0
    match = _compiled_re(pattern, flags).search("" if text is None else str(text))
    if match is None:
        return value.get("default", "")
    return match.group(1) if match.groups() else match.group(0)


def _op_regex_replace(value: Any, ctx: EvalContext) -> Any:
    text = _eval_value(value.get("value"), ctx)
    pattern = str(value.get("pattern", ""))
    replacement = str(value.get("replacement", ""))
    flags = re.IGNORECASE if value.get("ignorecase") else 0
    count = int(value.get("count", 0))
    return _compiled_re(pattern, flags).sub(replacement, "" if text is None else str(text), count=count)


def _op_age_days(value: Any, ctx: EvalContext) -> Any:
    text = _eval_value(value.get("value"), ctx)
    reference = _eval_value(value.get("reference"), ctx) if "reference" in value else None
    if not text:
        return value.get("default", 0.0)
    days = _age_days(text, reference)
    digits = value.get("round")
    return round(days, int(digits)) if digits is not None else days


def _op_find(value: Any, ctx: EvalContext) -> Any:
    source = _eval_value(value.get("source", []), ctx)
    if not isinstance(source, list):
        return value.get("default", {})
    where = value.get("where", {})
    for candidate in source:
        if isinstance(candidate, dict) and _eval_predicate(where, ctx.with_item(candidate, ctx.parent)):
            return candidate
    return value.get("default", {})


def _op_get(value: Any, ctx: EvalContext) -> Any:
    source = _eval_value(value.get("source", {}), ctx)
    key = _eval_value(value.get("key"), ctx)
    if isinstance(source, dict):
        return source.get(key, value.get("default"))
    return value.get("default")


def _op_index(value: Any, ctx: EvalContext) -> Any:
    raw_source = _eval_value(value.get("source", []), ctx)
    source = _coerce_iterable(raw_source) if not isinstance(raw_source, list) else raw_source
    key_spec = value.get("key")
    value_spec = value.get("value", "item")
    result: dict[Any, Any] = {}
    for source_item in source:
        row_ctx = ctx.with_item(source_item, ctx.parent)
        key = _eval_value(key_spec, row_ctx)
        if key is not None:
            result[key] = _eval_value(value_spec, row_ctx)
    return result


def _op_slice(value: Any, ctx: EvalContext) -> Any:
    source = _eval_value(value.get("source", []), ctx)
    if not isinstance(source, list):
        return []
    return source[slice(value.get("start"), value.get("stop"), value.get("step"))]


def _op_sort(value: Any, ctx: EvalContext) -> Any:
    source = _eval_value(value.get("source", []), ctx)
    if not isinstance(source, list):
        return []
    key_path = value.get("by")
    reverse = bool(value.get("reverse", False))
    if key_path is None:
        try:
            return sorted(source, reverse=reverse)
        except TypeError:
            return list(source)

    key_path_str = str(key_path)

    def _sort_key(row: Any) -> Any:
        resolved = _resolve_path(key_path_str, ctx.with_item(row, ctx.parent))
        return (resolved is None, resolved)

    return sorted(source, key=_sort_key, reverse=reverse)


def _op_unique(value: Any, ctx: EvalContext) -> Any:
    source = _eval_value(value.get("source", []), ctx)
    if not isinstance(source, list):
        return []
    key_path = value.get("by")
    seen: set[Any] = set()
    out: list[Any] = []
    for row in source:
        if key_path is None:
            k = row if isinstance(row, (str, int, float, bool, tuple)) else id(row)
        else:
            k = _resolve_path(str(key_path), ctx.with_item(row, ctx.parent))
            try:
                hash(k)
            except TypeError:
                k = repr(k)
        if k in seen:
            continue
        seen.add(k)
        out.append(row)
    return out


def _op_merge(value: Any, ctx: EvalContext) -> Any:
    # Sources are listed in *precedence* order: earlier wins. Build the
    # dict from least-precedence (last) to most-precedence (first) so the
    # final `update` writes the winning values.
    sources = value if isinstance(value, list) else value.get("sources", [])
    out_dict: dict[Any, Any] = {}
    for src_spec in reversed(sources):
        resolved = _eval_value(src_spec, ctx)
        if isinstance(resolved, dict):
            out_dict.update(resolved)
    return out_dict


def _op_defined(value: Any, ctx: EvalContext) -> Any:
    if isinstance(value, str):
        return _resolve_path(value, ctx) is not None
    return _eval_value(value, ctx) is not None


def _op_first_of(spec: dict[str, Any], ctx: EvalContext) -> Any:
    for candidate in spec["first_of"]:
        resolved = _eval_value(candidate, ctx)
        if _is_present(resolved):
            return resolved
    return spec.get("default")


def _op_if(spec: dict[str, Any], ctx: EvalContext) -> Any:
    if _eval_predicate_list(spec["if"], ctx):
        if "then" in spec:
            return _eval_value(spec["then"], ctx)
        return True
    if "else" in spec:
        return _eval_value(spec["else"], ctx)
    return None


# ---------------------------------------------------------------------------
# Operator registry. ``_DISPATCH_ORDER`` decides priority when a spec
# dict carries more than one operator key; single-key specs (the common
# case) bypass the ordering via the fast path in ``_eval_value``.
# ---------------------------------------------------------------------------


_HandlerFn = Callable[[Any, EvalContext], Any]


_OPS: dict[str, _HandlerFn] = {
    "const": _op_const,
    "path": _op_path,
    "from": _op_path,  # alias
    "flatten": _op_flatten,
    "template": _op_template,
    "expr": _op_expr,
    "compute": _op_expr,  # alias
    "object": _op_object,
    "list": _op_list,
    "count": _op_count,
    "pluck": _op_pluck,
    "truthy": _op_truthy,
    "lookup": _op_lookup,
    "regex_search": _op_regex_search,
    "regex_replace": _op_regex_replace,
    "age_days": _op_age_days,
    "find": _op_find,
    "get": _op_get,
    "index": _op_index,
    "slice": _op_slice,
    "sort": _op_sort,
    "unique": _op_unique,
    "merge": _op_merge,
    "defined": _op_defined,
}


_MultiKeyHandler = Callable[[dict[str, Any], EvalContext], Any]


_MULTI_KEY_OPS: dict[str, _MultiKeyHandler] = {
    # `first_of` reads sibling `default:`; `if` reads `then:` / `else:`.
    "first_of": _op_first_of,
    "if": _op_if,
}


# Single dispatch tuple — interleaves single-value and multi-key op
# names. Priority is the position in this tuple.
_DISPATCH_ORDER: tuple[str, ...] = (
    "const",
    "path",
    "from",
    "flatten",
    "template",
    "expr",
    "compute",
    "first_of",
    "object",
    "list",
    "count",
    "pluck",
    "truthy",
    "lookup",
    "regex_search",
    "regex_replace",
    "age_days",
    "find",
    "get",
    "index",
    "slice",
    "sort",
    "unique",
    "merge",
    "defined",
    "if",
)
_DISPATCH_KEYS: frozenset[str] = frozenset(_DISPATCH_ORDER)


# ---------------------------------------------------------------------------
# JSON-schema fragments for each operator. Consumed by
# ``generate_schema.py::_build_normalize_spec`` to emit the typed
# ``NormalizeSpec`` definition for IDE autocomplete. The import-time
# assertion at the bottom of this module enforces 1:1 coverage with the
# dispatched op set.
#
# Each entry has:
#   ``value``         JSON Schema for the operator's primary RHS.
#   ``extra_props``   sibling keys the multi-key op also reads
#                     (e.g. ``then``/``else`` for ``if``, ``default``
#                     for ``first_of``).
# ---------------------------------------------------------------------------


# `_OP_VALUE` is the freeform "any nested DSL value" reference shared
# across every operator's JSON-schema fragment. Encoded as a `$ref` so
# the generated JSON schema points at a single `OpValue` definition
# rather than inlining the same description dict at ~50 sites.
_OP_VALUE: dict[str, Any] = {"$ref": "#/$defs/OpValue"}
_OP_VALUE_DEF: dict[str, Any] = {"description": "Any DSL value: string path, scalar, or another operator dict."}


def _list_value_schema() -> dict[str, Any]:
    """The `list:` operator's RHS sub-schema (source/for_each/include_where/map/...)."""
    return {
        "type": "object",
        "properties": {
            "source": _OP_VALUE,
            "for_each": _OP_VALUE,
            "expand": {"type": "string"},
            "include_source": {"type": "boolean", "default": True},
            "include_where": _OP_VALUE,
            "exclude_where": _OP_VALUE,
            "exclude_match_any": {
                "type": "object",
                "properties": {"field": {"type": "string"}, "patterns": {"type": "array"}},
            },
            "map": {"type": "object", "additionalProperties": True},
        },
    }


_NORMALIZE_OP_SCHEMAS: dict[str, dict[str, Any]] = {
    "const": {"value": {}},
    "path": {"value": {"type": "string"}},
    "from": {"value": {"type": "string"}},
    "flatten": {"value": {"type": "string"}},
    "template": {"value": {"type": "string"}},
    "expr": {"value": {"type": "string"}},
    "compute": {"value": {"type": "string"}},
    "first_of": {
        "value": {"type": "array", "items": _OP_VALUE},
        "extra_props": {"default": _OP_VALUE},
    },
    "if": {
        "value": _OP_VALUE,
        "extra_props": {"then": _OP_VALUE, "else": _OP_VALUE},
    },
    "object": {"value": {"type": "object", "additionalProperties": True}},
    "merge": {"value": _OP_VALUE},
    "list": {"value": _list_value_schema()},
    "count": {"value": _OP_VALUE},
    "pluck": {
        "value": {
            "type": "object",
            "properties": {"source": _OP_VALUE, "path": {"type": "string"}},
        }
    },
    "slice": {
        "value": {
            "type": "object",
            "properties": {
                "source": _OP_VALUE,
                "start": {"type": ["integer", "null"]},
                "stop": {"type": ["integer", "null"]},
                "step": {"type": ["integer", "null"]},
            },
        }
    },
    "sort": {
        "value": {
            "type": "object",
            "properties": {
                "source": _OP_VALUE,
                "by": {"type": "string"},
                "reverse": {"type": "boolean", "default": False},
            },
        }
    },
    "unique": {
        "value": {
            "type": "object",
            "properties": {"source": _OP_VALUE, "by": {"type": "string"}},
        }
    },
    "truthy": {"value": _OP_VALUE},
    "lookup": {
        "value": {
            "type": "object",
            "properties": {"value": _OP_VALUE, "map": {"type": "object"}, "default": {}},
        }
    },
    "regex_search": {
        "value": {
            "type": "object",
            "properties": {
                "value": _OP_VALUE,
                "pattern": {"type": "string"},
                "ignorecase": {"type": "boolean"},
                "default": {"type": "string"},
            },
        }
    },
    "regex_replace": {
        "value": {
            "type": "object",
            "properties": {
                "value": _OP_VALUE,
                "pattern": {"type": "string"},
                "replacement": {"type": "string"},
                "ignorecase": {"type": "boolean"},
                "count": {"type": "integer", "default": 0, "description": "Max replacements; 0 = all."},
            },
            "required": ["pattern", "replacement"],
        }
    },
    "age_days": {
        "value": {
            "type": "object",
            "properties": {"value": _OP_VALUE, "reference": _OP_VALUE, "round": {"type": "integer"}, "default": {}},
        }
    },
    "find": {
        "value": {
            "type": "object",
            "properties": {"source": _OP_VALUE, "where": {"type": "object"}, "default": {}},
        }
    },
    "get": {
        "value": {
            "type": "object",
            "properties": {"source": _OP_VALUE, "key": _OP_VALUE, "default": {}},
        }
    },
    "index": {
        "value": {
            "type": "object",
            "properties": {"source": _OP_VALUE, "key": _OP_VALUE, "value": _OP_VALUE},
        }
    },
    "defined": {"value": _OP_VALUE},
}


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def _eval_value(spec: Any, ctx: EvalContext) -> Any:
    if spec is None:
        return None
    if isinstance(spec, str):
        if "{{" in spec or "{%" in spec:
            return _compile_template(spec).render(**ctx.merged())
        return _resolve_path(spec, ctx)
    if not isinstance(spec, dict):
        return spec

    # Fast path: scan the spec's own keys against the operator set —
    # 1-2 keys per spec in practice, so this is faster than walking
    # `_DISPATCH_ORDER` (26 entries) until we find the matching op.
    matched: list[str] = [k for k in spec if k in _DISPATCH_KEYS]
    if not matched:
        # Fallback: treat the whole dict as an `object:` shape.
        return {k: _eval_value(v, ctx) for k, v in spec.items()}
    op_key = matched[0] if len(matched) == 1 else next(k for k in _DISPATCH_ORDER if k in spec)
    if op_key in _MULTI_KEY_OPS:
        return _MULTI_KEY_OPS[op_key](spec, ctx)
    return _OPS[op_key](spec[op_key], ctx)


def eval_normalize(spec: Any, context: dict[str, Any]) -> Any:
    try:
        return _eval_value(spec, EvalContext(base=context))
    except Exception:
        logger.debug("normalize spec failed: %r", spec, exc_info=True)
        raise


# Drift guard: every dispatched op must have a JSON-schema fragment so the
# IDE's autocomplete stays in lockstep with the runtime evaluator.
if __debug__:
    _missing_schemas = _DISPATCH_KEYS - set(_NORMALIZE_OP_SCHEMAS)
    _orphan_schemas = set(_NORMALIZE_OP_SCHEMAS) - _DISPATCH_KEYS
    assert not _missing_schemas, f"_NORMALIZE_OP_SCHEMAS missing entries: {sorted(_missing_schemas)}"
    assert not _orphan_schemas, f"_NORMALIZE_OP_SCHEMAS has unknown ops: {sorted(_orphan_schemas)}"
    del _missing_schemas, _orphan_schemas
