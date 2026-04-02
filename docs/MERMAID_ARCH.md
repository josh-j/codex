# NCS Architecture Diagram

```mermaid
graph TB
    subgraph NCS["NCS — Network Control System"]

        subgraph Console["ncs-console &lpar;PowerShell/WPF GUI&rpar;"]
            WPF["WPF MainWindow<br/>&lpar;WebView2&rpar;"]
            Actions["actions.yml<br/>&lpar;Playbook Launcher&rpar;"]
            Settings["Settings &amp; Preflight"]
            Execution["Execution Module"]
            WPF --> Actions
            Actions --> Execution
            Settings --> Execution
        end

        subgraph Ansible["ncs-ansible &lpar;Ansible Collections + Playbooks&rpar;"]
            subgraph Playbooks["Playbooks"]
                Site["site.yml &lpar;Orchestrator&rpar;"]
                VMPlay["vmware/ &lpar;audit, stig, remediate&rpar;"]
                LinPlay["linux/ &lpar;audit, stig, remediate&rpar;"]
                WinPlay["windows/ &lpar;audit, stig, remediate&rpar;"]
                InfraPlay["infra/ &lpar;setup, networking&rpar;"]
                Site --> VMPlay & LinPlay & WinPlay & InfraPlay
            end

            subgraph Collections["Internal Collections"]
                Core["internal.core<br/>─ ncs_collector callback<br/>─ stig action plugin<br/>─ pwsh action plugin<br/>─ filter plugins"]
                VMColl["internal.vmware<br/>─ common, esxi, vcsa, vm roles"]
                LinColl["internal.linux<br/>─ ubuntu, photon roles"]
                WinColl["internal.windows<br/>─ windows role"]
                TplColl["internal.template<br/>─ scaffold collection"]
            end

            Playbooks -->|"uses roles"| Collections
            Core -->|"emits raw_*.yaml"| Artifacts["Telemetry Lake<br/>&lpar;raw_*.yaml artifacts&rpar;"]
        end

        subgraph Reporter["ncs-reporter &lpar;Python CLI&rpar;"]
            CLI["cli.py<br/>&lpar;Click entry point&rpar;"]
            Norm["normalization/<br/>─ schema-driven transforms<br/>─ STIG normalization<br/>─ alert evaluation"]
            Agg["aggregation.py<br/>&lpar;multi-host rollup&rpar;"]
            VM_["view_models/<br/>&lpar;Pydantic contracts&rpar;"]
            Render["renderers + templates<br/>&lpar;HTML dashboards&rpar;"]
            CKLB["cklb_export.py<br/>&lpar;STIG CKLB artifacts&rpar;"]
            Configs["configs/<br/>&lpar;YAML schemas&rpar;"]

            CLI --> Norm --> Agg --> VM_ --> Render
            CLI --> CKLB
            Configs --> Norm
        end

        Console -->|"launches playbooks"| Ansible
        Artifacts -->|"consumed by"| Reporter
        Reporter -->|"outputs"| Reports["Reports<br/>&lpar;/srv/samba/reports/&rpar;"]
    end

    Targets["Managed Fleet<br/>vCenter · ESXi · VMs<br/>Ubuntu · Photon · Windows"]
    Ansible <-->|"SSH / WinRM / API"| Targets
```

## Component Summary

| Component | Role | Tech |
|---|---|---|
| **ncs-console** | Operator GUI — launches playbooks, shows results | PowerShell + WPF/WebView2 |
| **ncs-ansible** | Stage 1 — Collect. Runs audit/STIG/remediate roles, emits `raw_*.yaml` telemetry | Ansible collections + playbooks |
| **ncs-reporter** | Stage 2 — Report. Normalizes raw data, evaluates alerts, renders HTML dashboards & CKLB | Python CLI (Click + Pydantic) |

## Data Flow

1. **Console** triggers Ansible playbooks via `actions.yml`
2. **Ansible** connects to managed fleet over SSH / WinRM / vSphere API
3. **`ncs_collector`** callback writes `raw_*.yaml` artifacts to the telemetry lake
4. **Reporter** reads artifacts → normalizes → aggregates → renders HTML reports and CKLB files
5. Reports are written to `/srv/samba/reports/`
