# internal.aci.apic

Collects Cisco ACI fabric telemetry by calling the APIC REST API.

## Behavior

Each APIC in `aci_apics` is logged into (via HTTPS, delegated to
localhost) and queried for:

- Fabric and tenant health scores
- Active faults (`faultInst.lc == "raised"`)
- Cleared faults from the last 24 hours
- Top ingress and egress port utilization (15-minute histogram)
- OSPF adjacency state
- Interface descriptions (for resolving DNs to human-readable labels)

Results are emitted via `internal.core.emit` to
`<report_dir>/platform/aci/apic/<host>/raw_apic.yaml`, where
`ncs-reporter` picks them up using the `aci` platform config.

## Variables

See `defaults/main.yaml`. At minimum, override `aci_username` and
`aci_password` from an inventory vault.

## Dispatch

`ncs_action` defaults to `collect`. No STIG or operation modes are
defined for ACI yet — the role is collection-only.
