"""Canonical rule for report-share paths.

Every tree node is a directory. The primary HTML report lives at
``<node>/<slug>.html``. Variants — STIG, historical snapshots — are
siblings named ``<node>/<slug>.<variant>.html`` or parked under
``<node>/history/<stamp>.html``. The collector writes raw telemetry into
the same directory as ``<node>/raw.yaml`` (or ``raw.<variant>.yaml``),
and the reporter's post-compute state lands at ``<node>/state.yaml``.

This module is the single source of truth for that rule; nowhere else in
the codebase should hardcode a report filename.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Iterable

_SLUGIFY_RE = re.compile(r"[^a-z0-9]+")
_SITE_SLUG = "site"


def slugify(name: str) -> str:
    """Normalize a free-form name (vCenter / Datacenter / Cluster) into a path segment.

    Lowercase, non-alphanumeric runs collapse to single hyphens, leading /
    trailing hyphens stripped. Uniqueness at a given tier is the caller's
    responsibility (parent-directory namespacing is usually enough).
    """
    if not isinstance(name, str):
        raise TypeError(f"slugify requires a string, got {type(name).__name__}")
    lowered = name.strip().lower()
    hyphenated = _SLUGIFY_RE.sub("-", lowered).strip("-")
    if not hyphenated:
        raise ValueError(f"slugify({name!r}) produced an empty slug")
    return hyphenated


class NodePath:
    """A node's position in the report tree, plus the filenames that live there.

    Construction takes the ordered segments from the tree root down to the
    node (root segment first). The ``slug`` is the node's own name — always
    the last segment. Use :meth:`child` to extend.

    Examples
    --------
    >>> root = NodePath.site()
    >>> root.html_path.as_posix()
    'site.html'
    >>> vsphere = NodePath.product('vsphere')
    >>> vsphere.html_path.as_posix()
    'vsphere/vsphere.html'
    >>> esxi = vsphere.child('vc-prod-01').child('dc-east').child('cluster-01').child('esxi-01')
    >>> esxi.html_path.as_posix()
    'vsphere/vc-prod-01/dc-east/cluster-01/esxi-01/esxi-01.html'
    >>> esxi.variant_path('stig').as_posix()
    'vsphere/vc-prod-01/dc-east/cluster-01/esxi-01/esxi-01.stig.html'
    >>> esxi.history_path('20260421T090000Z').as_posix()
    'vsphere/vc-prod-01/dc-east/cluster-01/esxi-01/history/20260421T090000Z.html'
    """

    __slots__ = ("_segments",)

    def __init__(self, segments: Iterable[str]) -> None:
        seg_tuple = tuple(segments)
        if not seg_tuple:
            raise ValueError("NodePath requires at least one segment")
        for s in seg_tuple:
            if not isinstance(s, str) or not s:
                raise ValueError(f"NodePath segment must be a non-empty string, got {s!r}")
        object.__setattr__(self, "_segments", seg_tuple)

    # Construction helpers -------------------------------------------------
    @classmethod
    def site(cls) -> NodePath:
        """The tree root. The one hardcoded sentinel."""
        return cls((_SITE_SLUG,))

    @classmethod
    def product(cls, product_slug: str) -> NodePath:
        """A top-level product directory (vsphere, ubuntu, photon, windows, aci).

        The product's own page sits at ``<product>/<product>.html`` — the slug
        repeats so the directory is self-describing.
        """
        return cls((product_slug,))

    def child(self, slug: str) -> NodePath:
        """Return a NodePath one level deeper under this one."""
        return NodePath((*self._segments, slug))

    # Accessors ------------------------------------------------------------
    @property
    def segments(self) -> tuple[str, ...]:
        return self._segments

    @property
    def slug(self) -> str:
        return self._segments[-1]

    @property
    def directory(self) -> PurePosixPath:
        """Directory containing this node's artifacts, relative to the report root.

        The *site* root is the report-share root itself, so site's directory is
        the share root (empty path). Every other node has its own directory.
        """
        if self._segments == (_SITE_SLUG,):
            return PurePosixPath(".")
        return PurePosixPath(*self._segments)

    # Artifact paths -------------------------------------------------------
    @property
    def html_path(self) -> PurePosixPath:
        """Primary HTML report path, relative to the report root."""
        filename = f"{self.slug}.html"
        if self._segments == (_SITE_SLUG,):
            return PurePosixPath(filename)
        return PurePosixPath(*self._segments) / filename

    def variant_path(self, variant: str, suffix: str = "html") -> PurePosixPath:
        """Path for a sibling variant of the primary report (e.g. ``stig`` → ``<slug>.stig.html``)."""
        if not variant or not variant.isidentifier():
            raise ValueError(f"variant must be a non-empty identifier, got {variant!r}")
        filename = f"{self.slug}.{variant}.{suffix}"
        if self._segments == (_SITE_SLUG,):
            return PurePosixPath(filename)
        return PurePosixPath(*self._segments) / filename

    def history_path(self, stamp: str, suffix: str = "html") -> PurePosixPath:
        """Historical snapshot path: ``<node>/history/<stamp>.<suffix>``."""
        if not stamp:
            raise ValueError("history stamp must be non-empty")
        base = self.directory
        return base / "history" / f"{stamp}.{suffix}"

    @property
    def raw_path(self) -> PurePosixPath:
        """Collector's raw telemetry file for this node."""
        return self.directory / "raw.yaml"

    def raw_variant_path(self, variant: str) -> PurePosixPath:
        """Collector's raw telemetry for a variant (``stig`` → ``raw.stig.yaml``)."""
        if not variant or not variant.isidentifier():
            raise ValueError(f"variant must be a non-empty identifier, got {variant!r}")
        return self.directory / f"raw.{variant}.yaml"

    @property
    def state_path(self) -> PurePosixPath:
        """Post-compute state file the reporter writes for this node."""
        return self.directory / "state.yaml"

    # Navigation -----------------------------------------------------------
    def parent(self) -> NodePath | None:
        if len(self._segments) <= 1:
            return None
        return NodePath(self._segments[:-1])

    def ancestors(self) -> list[NodePath]:
        """Return [root, ..., immediate-parent]. Excludes self and stops at site()."""
        out: list[NodePath] = []
        p = self.parent()
        while p is not None:
            out.append(p)
            p = p.parent()
        out.reverse()
        return out

    def resolve_under(self, root: Path) -> Path:
        """Materialize ``<root> / <segments>`` as a real filesystem path."""
        if self._segments == (_SITE_SLUG,):
            return root
        return root.joinpath(*self._segments)

    # Dunder ---------------------------------------------------------------
    def __eq__(self, other: object) -> bool:
        return isinstance(other, NodePath) and other._segments == self._segments

    def __hash__(self) -> int:
        return hash(self._segments)

    def __repr__(self) -> str:
        return f"NodePath({list(self._segments)!r})"

    def __str__(self) -> str:
        return self.html_path.as_posix()
