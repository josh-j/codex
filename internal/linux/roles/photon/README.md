# internal.linux.photon

Photon OS role that provides discovery and STIG audit/remediation actions for VMware Photon OS 5.0.

## Actions

- `discover`: Validate Photon host and emit discovery telemetry.
- `stig`: Run Photon STIG checks in check mode.
- `remediate`: Apply Photon STIG hardening controls.

## Notes

- STIG controls are sourced from VMware's Photon 5.0 V3R1 readiness guide content in this repository.
- Set `photon_stig_enable_hardening: true` to enforce controls.
