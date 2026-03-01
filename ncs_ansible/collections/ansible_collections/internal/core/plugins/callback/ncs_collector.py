# collections/ansible_collections/internal/core/plugins/callback/ncs_collector.py

import os
import tempfile
from datetime import datetime, timezone

import yaml
from ansible.plugins.callback import CallbackBase


class _IndentedDumper(yaml.Dumper):
    """PyYAML Dumper that indents block sequences under their parent key."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow=flow, indentless=False)

DOCUMENTATION = '''
    callback: ncs_collector
    type: aggregate
    short_description: Persists NCS raw collection data to disk from host stats
    description:
      - Intercepts 'ncs_collect' data from set_stats and writes it to the reporting directory.
      - Ensures that data collection remains persistent even after the playbook finishes.
'''

def _find_repo_root(start_dir: str, max_up: int = 8) -> str:
    cur = os.path.realpath(start_dir)
    for _ in range(max_up + 1):
        marker = os.path.join(cur, "collections", "ansible_collections")
        if os.path.isdir(marker):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.realpath(start_dir)

class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'aggregate'
    CALLBACK_NAME = 'ncs_collector'
    CALLBACK_NEEDS_ENABLED = True

    def __init__(self):
        super().__init__()
        self.repo_root = _find_repo_root(os.getcwd())

    def v2_playbook_on_stats(self, stats):
        """
        Triggered at the end of the playbook. Iterates through all hosts and
        persists any 'ncs_collect' data found in their stats.
        """
        for host in stats.processed.keys():
            custom_stats = stats.get_custom_stats(host)
            
            if not custom_stats or 'ncs_collect' not in custom_stats:
                continue

            collect_data = custom_stats['ncs_collect']
            if not isinstance(collect_data, dict):
                continue

            self._persist_host_data(host, collect_data)

    def _persist_host_data(self, host, collect_data):
        """
        Writes the collection payload and config to the appropriate disk paths.
        """
        platform = collect_data.get('platform', 'unknown')
        name = collect_data.get('name', 'raw')
        payload = collect_data.get('payload')
        config = collect_data.get('config')
        
        # Determine output directory
        report_dir = collect_data.get('report_directory') or '/srv/samba/reports'
        host_dir = os.path.join(report_dir, 'platform', platform, host)
        
        try:
            os.makedirs(host_dir, exist_ok=True)
        except OSError as e:
            self._display.warning(f"[ncs_collector] Could not create directory {host_dir}: {e}")
            return

        # 1. Save Raw Payload
        if payload is not None:
            raw_path = os.path.join(host_dir, f"raw_{name}.yaml")
            envelope = {
                'metadata': {
                    'host': host,
                    'raw_type': name,
                    'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'engine': 'ncs_collector_callback'
                },
                'data': payload
            }
            self._write_yaml(raw_path, envelope)

        # 2. Save Config if provided
        if config:
            config_path = os.path.join(host_dir, "config.yaml")
            config_envelope = {
                'metadata': {
                    'host': host,
                    'type': 'config',
                    'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                },
                'config': config
            }
            self._write_yaml(config_path, config_envelope)

    def _write_yaml(self, path, data):
        try:
            dir_ = os.path.dirname(path) or "."
            with tempfile.NamedTemporaryFile('w', dir=dir_, suffix='.tmp', delete=False, encoding='utf-8') as tmp:
                yaml.dump(data, tmp, Dumper=_IndentedDumper, default_flow_style=False, indent=2)
                tmp_path = tmp.name
            os.replace(tmp_path, path)
            self._display.display(f"[ncs_collector] Persisted data to {path}", color='green')
        except Exception as e:
            self._display.warning(f"[ncs_collector] Failed to write {path}: {e}")
