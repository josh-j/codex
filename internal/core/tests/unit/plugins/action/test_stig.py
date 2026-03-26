from __future__ import annotations

from dataclasses import dataclass

from ansible_collections.internal.core.plugins.action.stig import ActionModule


@dataclass
class _DummyTask:
    name: str

    def get_name(self) -> str:
        return self.name


def _build_action(task_name: str) -> ActionModule:
    action = ActionModule.__new__(ActionModule)
    action._task = _DummyTask(task_name)
    return action


def test_infer_stig_id_supports_numeric_and_prefixed_forms() -> None:
    action = _build_action("placeholder")

    assert action._infer_stig_id("stigrule_270741") == "270741"
    assert action._infer_stig_id("stigrule_270689a") == "270689a"
    assert action._infer_stig_id("stigrule_VCEM-70-000021") == "VCEM-70-000021"
    assert action._infer_stig_id("stigrule_VCLD-70-000056") == "VCLD-70-000056"
    assert action._infer_stig_id("stigrule_PHTN-30-000016") == "PHTN-30-000016"
    assert action._infer_stig_id("PostgreSQL | stigrule_VCPG-70-000014") == "VCPG-70-000014"
    assert action._infer_stig_id("query task without rule") is None


def test_check_stig_filter_supports_prefixed_stig_only_and_skip() -> None:
    action = _build_action("stigrule_VCEM-70-000021")

    allowed = action._check_stig_filter({"stig_only": ["VCEM-70-000021"]})
    assert allowed is None

    skipped = action._check_stig_filter({"stig_only": ["VCLD-70-000056"]})
    assert skipped is not None
    assert skipped["skipped"] is True
    assert skipped["stig"]["id"] == "VCEM-70-000021"

    denied = action._check_stig_filter({"stig_skip": ["VCEM-70-000021"]})
    assert denied is not None
    assert denied["skipped"] is True
    assert denied["stig"]["id"] == "VCEM-70-000021"


def test_check_stig_filter_preserves_numeric_base_matching() -> None:
    action = _build_action("stigrule_270689a")

    assert action._check_stig_filter({"stig_only": ["270689"]}) is None

    denied = action._check_stig_filter({"stig_skip": ["270689"]})
    assert denied is not None
    assert denied["skipped"] is True
    assert denied["stig"]["id"] == "270689a"


def test_evaluate_expr_supports_new_string_operators() -> None:
    action = _build_action("placeholder")
    task_vars = {
        "xml_line": '<Valve className="org.apache.catalina.valves.ErrorReportValve" showReport="false" showServerInfo="false"/>',
        "cipher": 'server.fips-mode                  = "enable"',
        "prefix": "vmware-services-envoy.conf",
        "suffix": "/etc/vmware-syslog/vmware-services-envoy.conf",
    }

    passed, details = action._evaluate_expr(
        [
            {"var": "xml_line", "equals_exact": '<Valve className="org.apache.catalina.valves.ErrorReportValve" showReport="false" showServerInfo="false"/>'},
            {"var": "cipher", "contains_exact": '                  = "enable"'},
            {"var": "prefix", "startswith": "vmware-services"},
            {"var": "suffix", "endswith": "vmware-services-envoy.conf"},
        ],
        task_vars,
    )

    assert passed is True
    assert details["prefix"] == "vmware-services-envoy.conf"


def test_evaluate_expr_preserves_existing_operator_behavior() -> None:
    action = _build_action("placeholder")

    passed, details = action._evaluate_expr(
        [
            {"var": "mode", "equals": "enable"},
            {"var": "ciphers", "equals_unordered": "tls1.2,tls1.3"},
            {"var": "log", "contains": "request"},
            {"var": "path", "matches": r"^/etc/.+conf$"},
            {"var": "value", "not_empty": True},
        ],
        {
            "mode": "ENABLE",
            "ciphers": "tls1.3,tls1.2",
            "log": "debug.log-request-handling",
            "path": "/etc/vmware-syslog.conf",
            "value": "present",
        },
    )

    assert passed is True
    assert details["mode"] == "ENABLE"
