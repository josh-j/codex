# Ubuntu 24.04 Lab

Disposable Ubuntu 24.04 LTS server lab hosted on `maas`. Driver is generated
from `hosts/nixos/maas/labs/ubuntu.nix` in the nix-config repo and exposed as
the `ulab` binary on `maas`.

## Topology

- Host: `maas` (libvirt / `qemu:///system`)
- Lab network: `ubuntu-lab` bridge, `10.80.0.0/24`
  - DHCP range: `10.80.0.100-10.80.0.200`
  - Gateway / DNS: `10.80.0.1`
- Guests:
  - `ubu01` — MAC `52:54:00:80:e5:01`, static `10.80.0.10`, 2 vCPU / 4 GiB / 30 GB

The `10.80.0.0/24` subnet is advertised over Tailscale by `maas`, so deck01 (and
the rest of the tailnet) can reach guests directly without port-forwarding.

## Lifecycle (run on maas)

```bash
ulab up        # tear down any prior ubu01, fetch cloud image if needed,
               # provision ubu01, wait for SSH, print inventory
ulab down      # destroy + undefine ubu01, remove qcow2/seed/cloud-init files
ulab status    # libvirt domstate + tcp/22 reachability
ulab inventory # print connection strings
```

The cloud image is cached at `/mnt/home/labs/ubuntu/noble-server-cloudimg-amd64.img`
and only re-downloaded if missing.

## Access

From deck01 (over Tailscale) or any host on the lab subnet:

```bash
ssh sio@10.80.0.10
```

Login is via SSH key — `cloud-init` seeds `sio` with `NOPASSWD` sudo and the
public key from `~sio/.ssh/authorized_keys` (or `~sio/.ssh/id_ed25519.pub`) on
`maas` at provisioning time.

## Console

If SSH is unreachable, attach to the serial console on maas:

```bash
ssh maas 'virsh -c qemu:///system console ubu01'
```

(Detach with `Ctrl-]`.)

## Reset

`ulab up` is idempotent — it always destroys any existing `ubu01` first, so
re-running it gives a clean VM from the cached cloud image.
