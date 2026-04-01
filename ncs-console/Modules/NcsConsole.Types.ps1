Set-StrictMode -Version Latest

enum NcsSshAuthMode {
    Agent
    KeyFile
    Password
}

class NcsConsoleSettings {
    [string] $SshHost = ""
    [int] $SshPort = 22
    [string] $SshUser = ""
    [string] $SshAuthMode = [NcsSshAuthMode]::Agent.ToString()
    [string] $SshKeyPath = ""
    [string] $SshKeyPassphrase = ""
    [string] $SshPassword = ""
    [string] $RemoteRepoPath = "~/ansible-ncs"
    [string] $LastAction = ""

    NcsConsoleSettings() {
    }
}

class NcsActionRequest {
    [string] $Playbook
    [string] $Limit = ""
    [string] $Tags = ""
    [bool] $CheckMode = $false
    [bool] $Diff = $false
    [string] $Verbosity = ""
    [string] $ExtraArgs = ""
    [hashtable] $Options = @{}
    [datetime] $RequestedAt = [datetime]::UtcNow

    NcsActionRequest([string] $Playbook) {
        $this.Playbook = $Playbook
    }
}

class NcsPreflightCheck {
    [string] $Name
    [bool] $Passed
    [string] $Message

    NcsPreflightCheck([string] $Name, [bool] $Passed, [string] $Message) {
        $this.Name = $Name
        $this.Passed = $Passed
        $this.Message = $Message
    }

    [string] ToString() {
        $prefix = if ($this.Passed) { "[OK]" } else { "[FAIL]" }
        return "$prefix $($this.Name) - $($this.Message)"
    }
}

class NcsPreflightResult {
    [bool] $IsReady = $false
    [System.Collections.Generic.List[NcsPreflightCheck]] $Checks = [System.Collections.Generic.List[NcsPreflightCheck]]::new()
    [System.Collections.Generic.List[string]] $BlockingIssues = [System.Collections.Generic.List[string]]::new()
    [string] $Banner = ""
}

class NcsRunResult {
    [string] $Action
    [string] $Command
    [int] $ExitCode = -1
    [bool] $Succeeded = $false
    [datetime] $StartedAt = [datetime]::UtcNow
    [Nullable[datetime]] $EndedAt
    [timespan] $Duration = [timespan]::Zero
    [string[]] $OutputLines = @()
    [string[]] $DetectedPaths = @()

    NcsRunResult() {
    }
}

function Get-NcsSshAuthModeNames {
    [NcsSshAuthMode].GetEnumNames()
}

function Import-NcsGroupedConfig {
    param(
        [Parameter(Mandatory)]
        [string] $Path
    )

    $lines = Get-Content -LiteralPath $Path
    $groups = [System.Collections.Generic.List[hashtable]]::new()
    $currentGroup = $null
    $currentItem = $null
    $currentOption = $null
    $inOptions = $false

    foreach ($line in $lines) {
        if ([string]::IsNullOrWhiteSpace($line) -or $line -match '^\s*#') { continue }

        if ($line -match '^- group:\s*(.+)$') {
            $currentGroup = @{ Group = $Matches[1].Trim(); Items = [System.Collections.Generic.List[hashtable]]::new() }
            $groups.Add($currentGroup)
            $currentItem = $null
            $currentOption = $null
            $inOptions = $false
            continue
        }

        if ($line -match '^\s{2,4}- label:\s*(.+)$' -and $null -ne $currentGroup) {
            $currentItem = @{ Label = $Matches[1].Trim() }
            $currentGroup.Items.Add($currentItem)
            $currentOption = $null
            $inOptions = $false
            continue
        }

        if ($line -match '^\s+options:\s*$' -and $null -ne $currentItem) {
            $currentItem['options'] = [System.Collections.Generic.List[hashtable]]::new()
            $inOptions = $true
            $currentOption = $null
            continue
        }

        if ($inOptions -and $line -match '^\s{6,10}- name:\s*(.+)$') {
            $currentOption = @{ name = $Matches[1].Trim() }
            $currentItem['options'].Add($currentOption)
            continue
        }

        if ($inOptions -and $null -ne $currentOption -and $line -match '^\s{8,12}(\w+):\s*(.+)$') {
            $key = $Matches[1].Trim()
            $rawVal = $Matches[2].Trim()
            if ($key -eq 'choices' -and $rawVal -match '^\[(.+)\]$') {
                $currentOption[$key] = @($Matches[1] -split ',' | ForEach-Object { $_.Trim() })
            } else {
                $currentOption[$key] = $rawVal
            }
            continue
        }

        if (-not $inOptions -and $line -match '^\s+(\w+):\s*(.+)$' -and $null -ne $currentItem) {
            $key = $Matches[1].Trim()
            $value = $Matches[2].Trim()
            if ($value -eq 'true') { $value = $true }
            elseif ($value -eq 'false') { $value = $false }
            $currentItem[$key] = $value
            continue
        }
    }

    return $groups
}

function Get-NcsRemotePlaybookTree {
    param(
        [Parameter(Mandatory)]
        [NcsConsoleSettings] $Settings
    )

    $repo = ConvertTo-NcsRemotePathExpression -Value $Settings.RemoteRepoPath
    $pyScript = @'
import os, json, yaml, re
SKIP_DIRS = {"templates", "test", "roles", "__pycache__"}
INTERNAL_VARS = {"ansible_python_interpreter", "ansible_connection", "ansible_become",
    "ansible_become_method", "ansible_user", "ansible_host", "ansible_port",
    "gather_facts", "connection", "become", "become_method", "become_user"}
READ_ONLY_KEYWORDS = {"collect", "audit", "health", "status", "search", "scan", "report",
    "verify", "discover", "summary"}
NAME_MAP = {"esxi": "ESXi", "vcsa": "VCSA", "vm": "VM", "vmware": "VMware", "ad": "AD"}

def auto_label(key):
    return key.replace("_", " ").title()

def yaml_str(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v) if v is not None else ""

def parse_option_line(key, value):
    """Parse compact option: 'name: type[choices] = default | label'"""
    opt = {"name": key}
    m = re.match(r'^(text|bool|select)(?:\[([^\]]+)\])?\s*(?:=\s*([^|]+))?\s*(?:\|\s*(.+))?$', value.strip())
    if m:
        typ, choices, default, label = m.groups()
        if typ and typ != "text":
            opt["type"] = typ
        if choices:
            opt["choices"] = [c.strip() for c in choices.split(",")]
        if default:
            opt["default"] = default.strip()
        if label:
            opt["label"] = label.strip()
        else:
            opt["label"] = auto_label(key)
    else:
        parts = value.split("|", 1)
        if len(parts) == 2:
            opt["default"] = parts[0].strip()
            opt["label"] = parts[1].strip()
        elif value.strip():
            opt["default"] = value.strip()
            opt["label"] = auto_label(key)
        else:
            opt["label"] = auto_label(key)
    return opt

def parse_ncs_blocks(path):
    """Parse # >>> / # <<< blocks. Entries within a block separated by # ---."""
    raw_blocks = []
    current = None
    with open(path) as fh:
        for raw in fh:
            stripped = raw.strip()
            if stripped == "# >>>":
                current = []
                continue
            if stripped == "# <<<":
                if current is not None:
                    raw_blocks.append(current)
                current = None
                continue
            if current is not None and stripped.startswith("#"):
                txt = stripped[2:] if stripped.startswith("# ") else stripped[1:]
                current.append(txt)
            elif current is None and not stripped.startswith("#") and stripped != "":
                break
    segments = []
    for lines in raw_blocks:
        segment = []
        for line in lines:
            if line.strip() == "---":
                if segment:
                    segments.append(segment)
                segment = []
            else:
                segment.append(line)
        if segment:
            segments.append(segment)
    result = []
    for lines in segments:
        try:
            data = yaml.safe_load("\n".join(lines))
            if not isinstance(data, dict):
                continue
            block = {}
            if "label" in data:
                block["label"] = data["label"]
            if not data.get("is_read_only"):
                block["mutating"] = True
            if "operation" in data:
                block["operation"] = data["operation"]
            if "options" in data and isinstance(data["options"], dict):
                block["options"] = [parse_option_line(k, yaml_str(v)) for k, v in data["options"].items()]
            result.append(block)
        except Exception:
            continue
    return result if result else None

def build_item(playbook, label, mutating=False, options=None):
    item = {"Label": label, "playbook": playbook}
    if mutating:
        item["mutating"] = True
    if options:
        item["options"] = options
    return item

def fallback_label(f, play=None):
    if play and isinstance(play, dict):
        name = play.get("name", "")
        label = re.sub(r"^[^|]+\|\s*", "", name).strip() if name else ""
        label = re.sub(r"^Phase\s+\d+\w*:\s*", "", label).strip()
        if label and "{{" not in label:
            return label
    return f.replace(".yml", "").replace(".yaml", "").replace("_", " ").title()

def fallback_options(play):
    if not play or not isinstance(play, dict):
        return []
    pvars = play.get("vars", {})
    if not isinstance(pvars, dict):
        return []
    opts = []
    for k, v in pvars.items():
        if k in INTERNAL_VARS or k.startswith(("ansible_", "ncs_", "_")):
            continue
        dv = yaml_str(v)
        if "{{" in dv:
            continue
        opts.append({"name": k, "label": auto_label(k), "default": dv})
    return opts

base = "playbooks"
groups = {}
for root, dirs, files in os.walk(base):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
    rel = os.path.relpath(root, base)
    raw_grp = "Fleet" if rel == "." else rel.replace(os.sep, "/").split("/")[0]
    grp = NAME_MAP.get(raw_grp, raw_grp.title())
    for f in sorted(files):
        if not f.endswith((".yml", ".yaml")) or f.startswith("_"):
            continue
        path = os.path.join(root, f)
        playbook = os.path.relpath(path, base).replace(os.sep, "/")
        try:
            with open(path) as fh:
                docs = yaml.safe_load(fh)
            if not isinstance(docs, list) or len(docs) == 0:
                continue
            play = docs[0]
            if not isinstance(play, dict):
                continue
            is_import = any(k.endswith("import_playbook") for k in play)
        except Exception:
            continue
        blocks = parse_ncs_blocks(path)
        if blocks:
            for blk in blocks:
                lbl = blk.get("label", fallback_label(f, None if is_import else play))
                mut = blk.get("mutating", False)
                opts = blk.get("options", [])
                op = blk.get("operation")
                if op:
                    opts = [{"name": "ncs_operation", "label": "Operation", "default": op}] + opts
                groups.setdefault(grp, []).append(build_item(playbook, lbl, mut, opts))
        else:
            lbl = fallback_label(f, None if is_import else play)
            stem = os.path.splitext(f)[0]
            mut = not any(k in stem for k in READ_ONLY_KEYWORDS)
            opts = fallback_options(play) if not is_import else []
            groups.setdefault(grp, []).append(build_item(playbook, lbl, mut, opts))
order = ["Fleet"] + sorted(k for k in groups if k != "Fleet")
print(json.dumps([{"Group": g, "Items": groups[g]} for g in order if g in groups]))
'@
    $command = "cd $repo && if [ -f .venv/bin/activate ]; then . .venv/bin/activate; fi && python3 << 'NCSPLAYBOOKS'" + "`n" + $pyScript + "`n" + "NCSPLAYBOOKS"
    $probe = Invoke-NcsSshProbe -Settings $Settings -RemoteCommand $command

    if ($probe.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($probe.StdOut)) {
        return @()
    }

    $data = $probe.StdOut | ConvertFrom-Json -AsHashtable
    $groups = [System.Collections.Generic.List[hashtable]]::new()

    foreach ($entry in @($data)) {
        if ($entry.ContainsKey('Items') -and @($entry['Items']).Length -gt 0) {
            $groups.Add($entry)
        }
    }

    return $groups
}

function Merge-NcsActionGroups {
    param(
        [Parameter(Mandatory)]
        $ConfigGroups,
        [Parameter(Mandatory)]
        $RemoteGroups
    )

    # Remote-first: use the remote scan as-is.
    # Config is only used to add entries whose playbook wasn't found remotely.
    $remotePlaybooks = [System.Collections.Generic.HashSet[string]]::new()
    foreach ($group in $RemoteGroups) {
        foreach ($item in $group.Items) {
            [void] $remotePlaybooks.Add($item['playbook'])
        }
    }

    $merged = [System.Collections.Generic.List[hashtable]]::new()
    $mergedGroupNames = [System.Collections.Generic.HashSet[string]]::new()
    foreach ($group in $RemoteGroups) {
        $mutableItems = [System.Collections.Generic.List[hashtable]]::new()
        foreach ($i in $group.Items) { $mutableItems.Add($i) }
        $merged.Add(@{ Group = $group.Group; Items = $mutableItems })
        [void] $mergedGroupNames.Add($group.Group)
    }

    foreach ($group in $ConfigGroups) {
        foreach ($item in $group.Items) {
            if ($remotePlaybooks.Contains($item['playbook'])) { continue }
            if ($mergedGroupNames.Contains($group.Group)) {
                foreach ($g in $merged) {
                    if ($g.Group -eq $group.Group) { $g.Items.Add($item); break }
                }
            } else {
                $newItems = [System.Collections.Generic.List[hashtable]]::new()
                $newItems.Add($item)
                $merged.Add(@{ Group = $group.Group; Items = $newItems })
                [void] $mergedGroupNames.Add($group.Group)
            }
        }
    }

    return $merged
}

function Get-NcsRemoteInventoryTree {
    param(
        [Parameter(Mandatory)]
        [NcsConsoleSettings] $Settings
    )

    $repo = ConvertTo-NcsRemotePathExpression -Value $Settings.RemoteRepoPath
    $command = "cd $repo && if [ -f .venv/bin/activate ]; then . .venv/bin/activate; fi && ansible-inventory -i inventory/production --list 2>/dev/null"
    $probe = Invoke-NcsSshProbe -Settings $Settings -RemoteCommand $command

    if ($probe.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($probe.StdOut)) {
        return @()
    }

    $inventory = $probe.StdOut | ConvertFrom-Json
    $groups = [System.Collections.Generic.List[hashtable]]::new()

    foreach ($key in @($inventory.PSObject.Properties.Name | Sort-Object)) {
        if ($key -in @('_meta', 'all', 'ungrouped')) { continue }

        $groupData = $inventory.$key
        if ($null -eq $groupData -or $null -eq $groupData.PSObject) { continue }

        $items = [System.Collections.Generic.List[hashtable]]::new()

        if ($groupData.PSObject.Properties.Name -contains 'children') {
            foreach ($child in @($groupData.children)) {
                $items.Add(@{ Label = $child; limit = $child })
            }
        }
        if ($groupData.PSObject.Properties.Name -contains 'hosts') {
            foreach ($h in @($groupData.hosts)) {
                $items.Add(@{ Label = $h; limit = $h })
            }
        }

        if ($items.Count -gt 0) {
            $groups.Add(@{ Group = $key; Items = $items })
        }
    }

    return $groups
}

