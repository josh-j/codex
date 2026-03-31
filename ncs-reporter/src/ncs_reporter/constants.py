"""Centralized constants for severity levels, health states, and STIG statuses.

All canonical string values used across the codebase are defined here so that
modules import named constants instead of duplicating string literals.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Alert severity levels
# ---------------------------------------------------------------------------

SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_WARNING = "WARNING"
SEVERITY_INFO = "INFO"

CRITICAL_ALIASES = frozenset({"CRITICAL", "CAT_I", "HIGH", "SEVERE", "FAILED"})
WARNING_ALIASES = frozenset({"WARNING", "WARN", "CAT_II", "MEDIUM", "MODERATE"})
INFO_ALIASES = frozenset({"CAT_III", "LOW"})

# ---------------------------------------------------------------------------
# Health states
# ---------------------------------------------------------------------------

HEALTH_HEALTHY = "HEALTHY"
HEALTH_OK = "OK"
HEALTH_WARNING = "WARNING"
HEALTH_CRITICAL = "CRITICAL"
HEALTH_UNKNOWN = "UNKNOWN"

# Aliases used by _status_from_health()
OK_STATUS_ALIASES = frozenset({"green", "healthy", "ok", "success", "pass", "passed"})
WARNING_STATUS_ALIASES = frozenset({"yellow", "warning", "degraded"})
CRITICAL_STATUS_ALIASES = frozenset({"red", "critical", "failed", "error"})
UNKNOWN_STATUS_ALIASES = frozenset({"gray", "unknown"})

# Badge presentation aliases
BADGE_OK_VALUES = frozenset({"OK", "HEALTHY", "GREEN", "PASS", "RUNNING", "SUCCESS"})
BADGE_FAIL_VALUES = frozenset({"CRITICAL", "RED", "FAILED", "FAIL", "STOPPED", "ERROR"})

# ---------------------------------------------------------------------------
# STIG finding statuses
# ---------------------------------------------------------------------------

STIG_STATUS_OPEN = "open"
STIG_STATUS_PASS = "pass"
STIG_STATUS_NA = "na"
STIG_STATUS_NOT_REVIEWED = "not_reviewed"
STIG_STATUS_ERROR = "error"
STIG_STATUS_UNKNOWN = "unknown"

STIG_OPEN_ALIASES = frozenset({"failed", "fail", "open", "finding", "non-compliant", "non_compliant"})
STIG_PASS_ALIASES = frozenset({
    "pass", "passed", "compliant", "success", "fixed", "remediated",
    "closed", "notafinding", "not_a_finding",
})
STIG_NA_ALIASES = frozenset({"na", "n/a", "not_applicable", "not applicable"})
STIG_NOT_REVIEWED_ALIASES = frozenset({"not_reviewed", "not reviewed", "unreviewed"})

# ---------------------------------------------------------------------------
# Injected virtual field names (schema-driven normalization)
# ---------------------------------------------------------------------------

FIELD_CRITICAL_COUNT = "_critical_count"
FIELD_WARNING_COUNT = "_warning_count"
FIELD_TOTAL_ALERTS = "_total_alerts"
