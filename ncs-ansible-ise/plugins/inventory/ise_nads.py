# -*- coding: utf-8 -*-
"""Cisco ISE NAD inventory plugin.

Turns the ISE PAN's ERS network-device list into an Ansible inventory:
each NAD becomes a host with C(ansible_host) set to its first
C(NetworkDeviceIPList) entry; ISE NDG hierarchy (Device Type, Location,
Ops Owner) is exposed as host vars (C(ise_device_type),
C(ise_location), C(ise_ops_owner), C(ise_groups)) so downstream
playbooks can target by C(keyed_groups) / C(compose).

Pairs with C(ise_network_devices_info) — same C(ErsClient) and
C(list_nads) helpers under C(plugins/module_utils/ers.py), so adding
a NAD column there shows up here too.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.inventory import BaseInventoryPlugin, Cacheable, Constructable

from ansible_collections.internal.ise.plugins.module_utils.ers import (
    ErsClient,
    fetch_details_concurrent,
    first,
    first_ip,
    list_nads,
    parse_ndg_list,
)


DOCUMENTATION = r"""
---
name: ise_nads
plugin_type: inventory
short_description: Cisco ISE NAD-derived Ansible inventory
description:
  - Pulls the network-device population from a Cisco ISE PAN via the
    ERS API and yields each NAD as an Ansible host with its NDG
    hierarchy attached as host vars.
  - Reuses C(plugins/module_utils/ers.py), so the HTTP client and
    pagination behavior match the C(ise_network_devices_info) module.
extends_documentation_fragment:
  - constructed
  - inventory_cache
options:
  plugin:
    description: Must be C(internal.ise.ise_nads).
    required: true
    type: str
    choices:
      - internal.ise.ise_nads
  hostname:
    description: ISE Primary Admin Node hostname (serves ERS).
    type: str
    required: true
  port:
    description: ERS port (defaults to ISE's stock 9060).
    type: int
    default: 9060
  username:
    description: ERS API username.
    type: str
    required: true
  password:
    description: ERS API password. Mark with C(!vault) in your inventory file.
    type: str
    required: true
  validate_certs:
    description: Verify the PAN's TLS certificate.
    type: bool
    default: false
  request_timeout:
    description: Per-request HTTPS timeout in seconds.
    type: int
    default: 60
  max_workers:
    description: ThreadPoolExecutor worker count for per-NAD detail fetches.
    type: int
    default: 16
  page_size:
    description: ERS page size for the list call (ISE caps at 100).
    type: int
    default: 100
  max_pages:
    description: Hard cap on pages walked, in case ISE reports a runaway total.
    type: int
    default: 100
  name_filter:
    description:
      - Narrow the inventory to NADs whose C(name) contains this
        substring (ERS server-side C(filter=name.CONTAINS.<value>)).
        Leave blank for the full fleet.
    type: str
    default: ""
  parent_group:
    description: Group every fetched NAD into this parent group.
    type: str
    default: ise_nads
"""

EXAMPLES = r"""
# inventory/ise.ise_nads.yaml
plugin: internal.ise.ise_nads
hostname: ise-pan.example.com
username: ers.readonly
password: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  3866...
validate_certs: false
name_filter: ""           # all NADs
parent_group: ise_nads
keyed_groups:
  - key: ise_device_type
    prefix: type
    separator: "_"
  - key: ise_location
    prefix: loc
    separator: "_"
  - key: ise_ops_owner
    prefix: ops
    separator: "_"
compose:
  ansible_network_os: "'ios' if ise_device_type == 'Switch' else None"
"""


class InventoryModule(BaseInventoryPlugin, Constructable, Cacheable):
    NAME = "internal.ise.ise_nads"

    def verify_file(self, path: str) -> bool:
        """Accept files named C(*.ise_nads.{yaml,yml}) — same convention
        the rest of the Ansible inventory ecosystem uses to disambiguate
        between plugin configs."""
        if not super().verify_file(path):
            return False
        return path.endswith((".ise_nads.yaml", ".ise_nads.yml"))

    def parse(self, inventory, loader, path, cache=True):  # type: ignore[override]
        super().parse(inventory, loader, path)
        self._read_config_data(path)

        cache_key = self.get_cache_key(path)
        user_cache = self.get_option("cache")
        attempt_to_read_cache = user_cache and cache
        cache_needs_update = user_cache and not cache

        nads: list[dict[str, Any]] | None = None
        if attempt_to_read_cache:
            try:
                nads = self._cache[cache_key]
            except KeyError:
                cache_needs_update = True

        if nads is None:
            nads = self._fetch_nads()

        if cache_needs_update:
            self._cache[cache_key] = nads

        parent_group = self.get_option("parent_group") or "ise_nads"
        self.inventory.add_group(parent_group)

        strict = self.get_option("strict")
        for nad in nads:
            self._emit_host(nad, parent_group, strict)

    def _fetch_nads(self) -> list[dict[str, Any]]:
        client = ErsClient(
            base_url=f"https://{self.get_option('hostname')}:{self.get_option('port')}",
            username=self.get_option("username"),
            password=self.get_option("password"),
            validate_certs=bool(self.get_option("validate_certs")),
            timeout=int(self.get_option("request_timeout")),
        )
        try:
            _, summaries = list_nads(
                client,
                page_size=int(self.get_option("page_size")),
                max_pages=int(self.get_option("max_pages")),
                name_filter=str(self.get_option("name_filter") or ""),
            )
        except RuntimeError as exc:
            raise AnsibleError(f"ise_nads: ERS list failed: {exc}") from exc

        details, errors = fetch_details_concurrent(
            client, summaries, int(self.get_option("max_workers"))
        )
        if errors:
            # One failed NAD shouldn't pull the whole inventory down — log
            # via the inventory display channel and keep going with what
            # we have.
            self.display.warning(
                f"ise_nads: {len(errors)} NAD detail fetch(es) failed; "
                f"first error: {errors[0].get('error')}"
            )
        return details

    def _emit_host(self, nad: dict[str, Any], parent_group: str, strict: bool) -> None:
        name = first(nad, ["name"], "")
        if not name:
            return
        ip = first_ip(nad)
        ndg = parse_ndg_list(nad.get("NetworkDeviceGroupList") or [])

        host_vars: dict[str, Any] = {
            "ansible_host": ip or name,
            "ise_id": first(nad, ["id"], ""),
            "ise_ip": ip,
            "ise_description": first(nad, ["description"], ""),
            "ise_profile_name": first(nad, ["profileName"], ""),
            "ise_model_name": first(nad, ["modelName"], ""),
            "ise_device_type": ndg["device_type"],
            "ise_location": ndg["location"],
            "ise_ops_owner": ndg["ops_owner"],
            "ise_groups": nad.get("NetworkDeviceGroupList") or [],
            "ise_has_radius": "authenticationSettings" in nad,
            "ise_has_tacacs": "tacacsSettings" in nad,
        }

        self.inventory.add_host(host=name, group=parent_group)
        for key, val in host_vars.items():
            self.inventory.set_variable(name, key, val)

        # Constructable hooks: compose / keyed_groups / groups from the
        # inventory YAML are applied here against the same host_vars dict.
        self._set_composite_vars(self.get_option("compose"), host_vars, name, strict=strict)
        self._add_host_to_composed_groups(self.get_option("groups"), host_vars, name, strict=strict)
        self._add_host_to_keyed_groups(self.get_option("keyed_groups"), host_vars, name, strict=strict)
