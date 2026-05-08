"""Repo-wide guardrails for the normalize DSL rollout.

Every reporter config under ``ncs-ansible-*/ncs_configs/*.yaml`` should
prefer ``normalize:`` over ad-hoc ``script:`` / ``template:`` producers,
and every ``roles/<sub_platform>/tasks/collect.yaml`` should emit raw
collector output without transforming ``set_fact`` blocks.

The rollout (``docs/ncs-reporter-config/NORMALIZE_DSL_ROLLOUT.md``) has
retired the obvious offenders; these tests fail if a new one creeps in.

Adding a justified escape hatch is OK — it just needs to be added to the
``ALLOWED_*`` lists below alongside a comment explaining why the DSL
isn't sufficient.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
COLLECTION_CONFIG_DIRS = sorted(REPO_ROOT.glob("ncs-ansible-*/ncs_configs"))
COLLECTION_ROLE_DIRS = sorted(REPO_ROOT.glob("ncs-ansible-*/roles"))

assert COLLECTION_CONFIG_DIRS, (
    f"Guardrail expected at least one ncs-ansible-*/ncs_configs dir under {REPO_ROOT!r}; "
    "if the reporter has been moved out of the umbrella repo, update REPO_ROOT."
)


@functools.cache
def _load_yaml_docs(paths: tuple[Path, ...]) -> tuple[tuple[str, Any], ...]:
    """Parse each YAML once per pytest session and return (rel_path, doc) pairs."""
    out: list[tuple[str, Any]] = []
    for p in paths:
        with p.open() as fh:
            out.append((str(p.relative_to(REPO_ROOT)), yaml.safe_load(fh) or {}))
    return tuple(out)

# (config_path_relative_to_repo_root, field_name) -> reason
ALLOWED_SCRIPT_FIELDS: dict[tuple[str, str], str] = {}
ALLOWED_TEMPLATE_FIELDS: dict[tuple[str, str], str] = {}

# (collect.yaml path relative to REPO_ROOT, set_fact name) -> reason
# Underscore-prefixed names are treated as private transients (per the
# rollout doc's playbook-side rule #4) and skipped by the check.
ALLOWED_SHAPING_SET_FACTS: dict[tuple[str, str], str] = {}

# Smells that indicate playbook-side shaping rather than a raw emit.
SHAPING_SMELLS = re.compile(
    r"\bselectattr\b"
    r"|\bitems2dict\b"
    r"|\bmap\(attribute\b"
    r"|\b\|\s*zip\b"
    r"|\bdict2items\b"
    r"|\brejectattr\b",
)


def _walk_field_specs(node, path: tuple[str, ...] = ()):
    """Yield (field_name, spec_dict) for every leaf field under top-level
    ``vars:`` blocks (and any other dict whose values look like field specs).
    """
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if not isinstance(value, dict):
            continue
        if any(k in value for k in ("path", "compute", "normalize", "template", "script", "const")):
            yield key, value
        else:
            yield from _walk_field_specs(value, path + (str(key),))


@functools.cache
def _all_collection_configs() -> tuple[tuple[str, Any], ...]:
    paths: list[Path] = []
    for cfg_dir in COLLECTION_CONFIG_DIRS:
        paths.extend(sorted(cfg_dir.glob("*.yaml")))
    return _load_yaml_docs(tuple(paths))


def test_no_script_fields_outside_allowlist() -> None:
    offenders: list[str] = []
    for rel, doc in _all_collection_configs():
        for field_name, spec in _walk_field_specs(doc):
            if "script" not in spec:
                continue
            key = (rel, field_name)
            if key in ALLOWED_SCRIPT_FIELDS:
                continue
            offenders.append(f"{rel}: field '{field_name}' uses script:")
    assert not offenders, (
        "New script: fields detected. Prefer normalize:; if the DSL truly "
        "cannot express it, add the field to ALLOWED_SCRIPT_FIELDS with a "
        "justification.\n  " + "\n  ".join(offenders)
    )


@functools.cache
def _all_collect_tasks() -> tuple[tuple[str, Any], ...]:
    paths: list[Path] = []
    for roles_dir in COLLECTION_ROLE_DIRS:
        paths.extend(sorted(roles_dir.glob("*/tasks/collect.yaml")))
    return _load_yaml_docs(tuple(paths))


def _iter_set_facts(node, path: tuple[int, ...] = ()):
    """Yield each set_fact dict in an Ansible task tree."""
    if isinstance(node, list):
        for i, item in enumerate(node):
            yield from _iter_set_facts(item, path + (i,))
    elif isinstance(node, dict):
        sf = node.get("ansible.builtin.set_fact") or node.get("set_fact")
        if isinstance(sf, dict):
            yield sf
        for nested_key in ("block", "rescue", "always"):
            if nested_key in node:
                yield from _iter_set_facts(node[nested_key], path + (-1,))


def test_no_shaping_set_facts_in_collect_tasks() -> None:
    offenders: list[str] = []
    for rel, doc in _all_collect_tasks():
        for sf in _iter_set_facts(doc):
            for name, expr in sf.items():
                if name.startswith("_"):
                    continue
                if (rel, name) in ALLOWED_SHAPING_SET_FACTS:
                    continue
                if not isinstance(expr, str):
                    continue
                if SHAPING_SMELLS.search(expr):
                    offenders.append(f"{rel}: set_fact '{name}' uses shaping filters")
    assert not offenders, (
        "Transforming set_fact blocks detected in collect tasks. Move the "
        "shaping into the matching schema's normalize: spec; if the run "
        "really needs a private transform, prefix the fact with '_' so it "
        "isn't emitted, or add it to ALLOWED_SHAPING_SET_FACTS with a "
        "justification.\n  " + "\n  ".join(offenders)
    )


def test_no_template_fields_outside_allowlist() -> None:
    offenders: list[str] = []
    for rel, doc in _all_collection_configs():
        for field_name, spec in _walk_field_specs(doc):
            if "template" not in spec:
                continue
            key = (rel, field_name)
            if key in ALLOWED_TEMPLATE_FIELDS:
                continue
            offenders.append(f"{rel}: field '{field_name}' uses template:")
    assert not offenders, (
        "New template: fields detected. Prefer normalize:; if the DSL "
        "truly cannot express it, add the field to ALLOWED_TEMPLATE_FIELDS "
        "with a justification.\n  " + "\n  ".join(offenders)
    )
