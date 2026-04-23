# NCS Architecture Diagram

```mermaid
graph TB
    subgraph NCS["NCS - Non-Core Services"]

        subgraph Console["ncs-console (Operator GUI)"]
            WPF["WPF MainWindow<br>(WebView2)"]
            Actions["actions.yml<br>(Action Registry)"]
            Settings["Settings and Preflight"]
            Execution["Execution Module"]
            WPF --> Actions
            Actions --> Execution
            Settings --> Execution
        end

        subgraph Ansible["ncs-ansible (Collection and Playbook Engine)"]
            subgraph Playbooks["Playbooks"]
                Site["site.yml (Orchestrator)"]
                PlatA["platform-a playbooks"]
                PlatB["platform-b playbooks"]
                PlatN["platform-n playbooks"]
                Site --> PlatA
                Site --> PlatB
                Site --> PlatN
            end

            subgraph Collections["Internal Collections"]
                Core["internal.core<br>- ncs_collector callback<br>- action plugins<br>- filter plugins"]
                CollA["internal.platform-a<br>- platform roles"]
                CollB["internal.platform-b<br>- platform roles"]
                CollN["internal.platform-n<br>- platform roles"]
                TplColl["internal.template<br>- scaffold for new collections"]
            end

            Playbooks -->|"uses roles"| Collections
            Core -->|"emits raw_*.yaml"| Artifacts["Telemetry Lake<br>(raw_*.yaml artifacts)"]
        end

        subgraph Reporter["ncs-reporter (Reporting Engine)"]
            CLI["CLI (Click entry point)"]
            Configs["configs/<br>(YAML report schemas)"]
            Norm["normalization/<br>- schema-driven transforms<br>- alert evaluation"]
            Agg["aggregation<br>(multi-host rollup)"]
            VMod["view models<br>(Pydantic contracts)"]
            Render["renderers + templates<br>(HTML / custom formats)"]
            Export["export modules<br>(pluggable output formats)"]

            CLI --> Norm
            Norm --> Agg
            Agg --> VMod
            VMod --> Render
            CLI --> Export
            Configs --> Norm
        end

        Console -->|"launches playbooks"| Ansible
        Artifacts -->|"consumed by"| Reporter
        Reporter -->|"outputs"| Reports["Reports and Artifacts"]
    end

    Targets["Managed Infrastructure<br>(any platform reachable by Ansible)"]
    Ansible <-->|"SSH / WinRM / API"| Targets
```

## Component Summary

| Component | Role | Tech |
|---|---|---|
| **ncs-console** | Operator GUI — action launcher and preflight checks | PowerShell + WPF/WebView2 |
| **ncs-ansible** | Stage 1 — Collect. Runs platform roles via playbooks, emits structured `raw_*.yaml` telemetry via the `ncs_collector` callback | Ansible collections + playbooks |
| **ncs-reporter** | Stage 2 — Report. Schema-driven normalization, alerting, aggregation, and rendering into dashboards and export artifacts | Python CLI (Click + Pydantic) |

## Data Flow

1. **Console** selects an action from the registry and launches the corresponding Ansible playbook
2. **Ansible** connects to managed infrastructure over SSH / WinRM / platform APIs
3. Platform roles collect data; the **`ncs_collector`** callback persists results as `raw_*.yaml` artifacts
4. **Reporter** reads artifacts → normalizes via config-driven schemas → aggregates across hosts → renders reports and export artifacts
5. Output is written to a configurable report destination
