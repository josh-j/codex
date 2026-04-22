# NCS Architecture Diagram

```mermaid
graph TB
    subgraph NCS["NCS — Non-Core Services"]

        subgraph Console["ncs-console &lpar;Operator GUI&rpar;"]
            WPF["WPF MainWindow<br/>&lpar;WebView2&rpar;"]
            Actions["actions.yml<br/>&lpar;Action Registry&rpar;"]
            Settings["Settings &amp; Preflight"]
            Execution["Execution Module"]
            WPF --> Actions
            Actions --> Execution
            Settings --> Execution
        end

        subgraph Ansible["ncs-ansible &lpar;Collection &amp; Playbook Engine&rpar;"]
            subgraph Playbooks["Playbooks"]
                Site["site.yml &lpar;Orchestrator&rpar;"]
                PlatA["platform-a/ playbooks"]
                PlatB["platform-b/ playbooks"]
                PlatN["platform-n/ playbooks"]
                Site --> PlatA & PlatB & PlatN
            end

            subgraph Collections["Internal Collections"]
                Core["internal.core<br/>─ ncs_collector callback<br/>─ action plugins<br/>─ filter plugins"]
                CollA["internal.&lt;platform-a&gt;<br/>─ platform roles"]
                CollB["internal.&lt;platform-b&gt;<br/>─ platform roles"]
                CollN["internal.&lt;platform-n&gt;<br/>─ platform roles"]
                TplColl["internal.template<br/>─ scaffold for new collections"]
            end

            Playbooks -->|"uses roles"| Collections
            Core -->|"emits raw_*.yaml"| Artifacts["Telemetry Lake<br/>&lpar;raw_*.yaml artifacts&rpar;"]
        end

        subgraph Reporter["ncs-reporter &lpar;Reporting Engine&rpar;"]
            CLI["CLI &lpar;Click entry point&rpar;"]
            Configs["configs/<br/>&lpar;YAML report schemas&rpar;"]
            Norm["normalization/<br/>─ schema-driven transforms<br/>─ alert evaluation"]
            Agg["aggregation<br/>&lpar;multi-host rollup&rpar;"]
            VM_["view models<br/>&lpar;Pydantic contracts&rpar;"]
            Render["renderers + templates<br/>&lpar;HTML / custom formats&rpar;"]
            Export["export modules<br/>&lpar;pluggable output formats&rpar;"]

            CLI --> Norm --> Agg --> VM_ --> Render
            CLI --> Export
            Configs --> Norm
        end

        Console -->|"launches playbooks"| Ansible
        Artifacts -->|"consumed by"| Reporter
        Reporter -->|"outputs"| Reports["Reports &amp; Artifacts"]
    end

    Targets["Managed Infrastructure<br/>&lpar;any platform reachable by Ansible&rpar;"]
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
