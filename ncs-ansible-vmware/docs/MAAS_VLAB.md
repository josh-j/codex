# Testing against the maas vlab

The `internal.vmware` collection has no mocking — tests run against a
real vCenter API. This doc covers the canonical lab: a nested vSphere
environment built on `maas` and reachable from `deck01` via tailscale.

## Lab summary

| Component | IP          | Notes                                  |
|-----------|-------------|----------------------------------------|
| vCenter   | 10.78.0.20  | `administrator@vsphere.local` / `VMware123!` |
| esxi01    | 10.78.0.10  | `root` / `VMware123`                   |
| esxi02    | 10.78.0.11  | `root` / `VMware123`                   |

vCenter manages a single datacenter `lab-dc` containing one cluster
`lab-cluster` with both ESXi hosts. A stub VM `lab-guest01` sits on
`esxi02` for VM-targeted STIG audits.

`maas` advertises `10.78.0.0/24` over tailscale, so `deck01` reaches
all three IPs directly.

## Build / teardown (run from deck01)

```sh
ssh maas vlab up        # 25-45 min, idempotent
ssh maas vlab status    # snapshot of reachability
ssh maas vlab down      # nuke lab state
```

Full topology, internals, and storage layout: see
`maas-vlab.md` in the nix-config mdBook
(`/srv/nix-config/docs/src/maas-vlab.md` on maas, or `just docs-serve`).

## Inventory

`tests/inventory/` (gitignored) is pre-populated against this lab.
Re-create after a fresh checkout:

```sh
ssh maas vlab inventory   # prints the values you need to plug in
```

The committed example at `tests/inventory.example/` is a generic
skeleton; the maas-vlab inventory uses the same shape with these
hosts:

- `vcsa.maas-lab` (`ansible_host: 10.78.0.20`) in group `vcsa`
- `esxi01.maas-lab`, `esxi02.maas-lab` in group `esxi_hosts`

Lab credentials are intentionally not vaulted — they are fixed,
weak, and embedded in the `vlab` script so the lab is fully
reproducible. `tests/.vault_pass` only needs to exist (any string)
to satisfy `ansible-playbook --vault-password-file`.

## Test loop

```sh
cd ~/codex/ncs-ansible-vmware
just test         # esxi_collect.yml in --check mode (read-only)
just test-apply   # full STIG remediation; mutates the lab
```

To return the lab to a known-good state between runs:

```sh
ssh maas vlab down && ssh maas vlab up
```

The build is the source of truth; there are no snapshots to roll
back to, just rebuild from scratch.
