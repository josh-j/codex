# Core Callback Plugins

This directory contains Ansible callback plugins critical for the NCS reporting pipeline. 

Unlike traditional Ansible setups where data is manipulated within tasks and templates, NCS relies on these callbacks to decouple **data collection** from **reporting**.

## `ncs_collector.py`
The primary bridge between Ansible execution and the `ncs_reporter` Python CLI. 
It intercepts stats emitted by target hosts via `ansible.builtin.set_stats` (under the `ncs_collect` key) and persists them to disk as `raw_*.yaml` payload files. This ensures raw telemetry is safely decoupled and ready for standalone Python processing.

## `stig_xml.py`
A specialized plugin for STIG compliance testing. 
It listens to task outcomes during playbook execution and automatically generates STIG XCCDF XML and JSON results based on task pass/fail states. It is designed to run in both apply and check-modes, attributing results appropriately even when execution occurs on `localhost` (e.g. against APIs like vCenter).
