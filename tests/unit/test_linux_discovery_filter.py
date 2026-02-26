import importlib.util
import pathlib
import unittest
from typing import Any

MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "linux"
    / "plugins"
    / "filter"
    / "discovery.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("linux_discovery_filter", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LinuxDiscoveryFilterTests(unittest.TestCase):
    module: Any
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_build_storage_inventory_filters_loop_and_computes_usage(self):
        out = self.module.build_storage_inventory(
            [
                {"device": "/dev/sda1", "mount": "/", "fstype": "ext4", "size_total": 100, "size_available": 25},
                {
                    "device": "/dev/loop0",
                    "mount": "/snap/x",
                    "fstype": "squashfs",
                    "size_total": 10,
                    "size_available": 0,
                },
                {"device": "tmpfs", "mount": "/run", "fstype": "tmpfs", "size_total": 10, "size_available": 5},
            ]
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["device"], "/dev/sda1")
        self.assertEqual(out[0]["used_pct"], 75.0)

    def test_build_user_inventory_parses_shadow_age(self):
        out = self.module.build_user_inventory(
            {"alice": ["x", "1000", "1000", "", "/home/alice", "/bin/bash"]},
            ["alice:*:20000:0:99999:7:::"],
            20010 * 86400,
        )
        self.assertEqual(out[0]["name"], "alice")
        self.assertEqual(out[0]["uid"], "1000")
        self.assertEqual(out[0]["password_age_days"], 10)

    def test_parse_sshd_config_and_collect_file_stats(self):
        ssh = self.module.parse_sshd_config(["PermitRootLogin no", "MaxAuthTries 3", "badline"])
        self.assertEqual(ssh["PermitRootLogin"], "no")
        self.assertEqual(ssh["MaxAuthTries"], "3")

        fstats = self.module.collect_existing_file_stats(
            [
                {"item": "/etc/ssh/sshd_config", "stat": {"exists": True, "mode": "0600"}},
                {"item": "/missing", "stat": {"exists": False}},
                {"item": "/bad", "stat": None},
            ]
        )
        self.assertIn("/etc/ssh/sshd_config", fstats)
        self.assertNotIn("/missing", fstats)


if __name__ == "__main__":
    unittest.main()
