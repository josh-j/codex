from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
REPORTER_RESOLVER = ROOT.parent / "ncs_reporter" / "src" / "ncs_path_contract" / "resolver.py"
MODULE_UTILS_RESOLVER = (
    ROOT
    / "collections"
    / "ansible_collections"
    / "internal"
    / "core"
    / "plugins"
    / "module_utils"
    / "path_contract.py"
)
PLATFORMS_CFG = ROOT / "files" / "ncs_reporter_configs" / "platforms.yaml"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestPathContractParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rep = _load_module(REPORTER_RESOLVER, "reporter_contract")
        cls.mod = _load_module(MODULE_UTILS_RESOLVER, "module_utils_contract")
        cls.raw = yaml.safe_load(PLATFORMS_CFG.read_text(encoding="utf-8")) or {}

    def test_required_keys_match(self) -> None:
        self.assertEqual(self.rep.REQUIRED_PATH_KEYS, self.mod.REQUIRED_PATH_KEYS)

    def test_validate_config_parity(self) -> None:
        rp = self.rep.validate_platforms_config_dict(dict(self.raw))
        mp = self.mod.validate_platforms_config_dict(dict(self.raw))
        self.assertEqual(len(rp), len(mp))

    def test_duplicate_target_type_parity(self) -> None:
        bad = {"platforms": self.raw["platforms"] + [dict(self.raw["platforms"][0])]}
        with self.assertRaises(ValueError):
            self.rep.validate_platforms_config_dict(bad)
        with self.assertRaises(ValueError):
            self.mod.validate_platforms_config_dict(bad)

    def test_unknown_target_resolution_parity(self) -> None:
        rp = self.rep.validate_platforms_config_dict(dict(self.raw))
        mp = self.mod.validate_platforms_config_dict(dict(self.raw))
        with self.assertRaises(ValueError):
            self.rep.resolve_platform_for_target_type(rp, "nope")
        with self.assertRaises(ValueError):
            self.mod.resolve_platform_for_target_type(mp, "nope")


if __name__ == "__main__":
    unittest.main()
