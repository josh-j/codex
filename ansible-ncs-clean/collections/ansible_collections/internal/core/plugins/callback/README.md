# Core Callback Plugins

This directory contains Ansible callback plugins critical for the NCS reporting pipeline. 

Unlike traditional Ansible setups where data is manipulated within tasks and templates, NCS relies on these callbacks to decouple **data collection** from **reporting**.

## `ncs_collector.py`
The primary bridge between Ansible execution and the `ncs_reporter` Python CLI. 
It intercepts stats emitted by target hosts via `ansible.builtin.set_stats` (under the `ncs_collect` key) and persists them to disk as `raw_*.yaml` payload files. This ensures raw telemetry is safely decoupled and ready for standalone Python processing.

## STIG Handling
STIG task outcomes are now captured directly by `ncs_collector.py` (runner event hooks + `ncs_collect` stats), and persisted as `raw_stig_*.yaml` envelopes compatible with `ncs_reporter`.
