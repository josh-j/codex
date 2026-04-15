Set-StrictMode -Version Latest

enum NcsSshAuthMode {
    Agent
    KeyFile
    Password
}

enum NcsReportDeliveryMode {
    Auto
    Smb
    Scp
}

enum NcsReportSource {
    Unavailable
    Smb
    Scp
}

class NcsScheduleEntry {
    [string] $Name = ""
    [string] $Description = ""
    [string] $Playbook = ""
    [string] $Calendar = ""
    [string] $Limit = ""
    [string] $Tags = ""
    [string] $ExtraArgs = ""
    [bool]   $CheckMode = $false
    [bool]   $Enabled = $true
    [bool]   $NotifyOnFailure = $true
    [int]    $TimeoutMinutes = 120
    # Transient fields populated from systemctl (not serialized to YAML)
    [string] $LastTrigger = ""
    [string] $NextTrigger = ""
    [string] $LastResult = ""
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
    [string] $RemoteReportsPath = "/srv/samba/reports"
    [string] $SmbShareName = "reports"
    [string] $SmbUser = "ansible"
    [string] $SmbPassword = ""
    [string] $ReportDeliveryMode = [NcsReportDeliveryMode]::Auto.ToString()
    [int]    $AutoRefreshIntervalSeconds = 5
    [string] $StrictHostKeyChecking = "accept-new"
    [int] $ConnectTimeoutSeconds = 10
    [int] $ServerAliveIntervalSeconds = 15
    [int] $ServerAliveCountMax = 3
    [string] $LogDirectory = ""
    [int] $SettingsVersion = 3
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
    [string] $Id
    [string] $Stage
    [string] $Name
    [bool] $Passed
    [string] $Message

    NcsPreflightCheck([string] $Id, [string] $Stage, [string] $Name, [bool] $Passed, [string] $Message) {
        $this.Id = $Id
        $this.Stage = $Stage
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
    [datetime] $CheckedAt = [datetime]::UtcNow
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
    [string] $FailureStage = ""
    [string] $FailureReason = ""
    [bool] $WasCancelled = $false
    [string] $SessionLogPath = ""
    [int] $RemotePid = 0
    [Nullable[datetime]] $PreflightCheckedAt

    NcsRunResult() {
    }
}

function Get-NcsSshAuthModeNames {
    [NcsSshAuthMode].GetEnumNames()
}

function Get-NcsRemotePlaybookTree {
    param(
        [Parameter(Mandatory)]
        [NcsConsoleSettings] $Settings
    )

    $pyScript = @'
import os, json, yaml, re
SKIP_DIRS = {"templates", "test", "roles", "__pycache__", "core", "group_vars"}
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
    """Parse compact option: 'name: type[choices] = default | label | tooltip'"""
    opt = {"name": key}
    # Split off tooltip (after second |) before parsing type/default/label
    segments = value.split("|")
    main_part = segments[0].strip()
    label_part = segments[1].strip() if len(segments) > 1 else ""
    tooltip_part = segments[2].strip() if len(segments) > 2 else ""
    if tooltip_part:
        opt["tooltip"] = tooltip_part
    # Recombine main + label for the type regex (first two segments only)
    combined = main_part + (" | " + label_part if label_part else "")
    m = re.match(r'^(text|bool|select)(?:\[([^\]]+)\])?\s*(?:=\s*([^|]+))?\s*(?:\|\s*(.+))?$', combined.strip())
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
        if label_part:
            opt["default"] = main_part
            opt["label"] = label_part
        elif main_part:
            opt["default"] = main_part
            opt["label"] = auto_label(key)
        else:
            opt["label"] = auto_label(key)
    return opt

def parse_ncs_blocks(text):
    """Parse # >>> / # <<< blocks from file text. Entries within a block separated by # ---."""
    raw_blocks = []
    current = None
    for raw in text.splitlines():
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

def get_node(tree, segments):
    cur = tree
    for i, seg in enumerate(segments):
        if seg not in cur:
            return None
        if i < len(segments) - 1:
            cur = cur[seg]["children"]
        else:
            return cur[seg]
    return None

def add_item(tree, segments, item):
    """Add item to the node at segments path, creating nodes as needed."""
    # Ensure all nodes exist
    cur = tree
    for seg in segments:
        if seg not in cur:
            cur[seg] = {"items": [], "children": {}}
        cur = cur[seg]["children"]
    # Now add item to the target node
    node = get_node(tree, segments)
    node["items"].append(item)

base = "playbooks"
tree = {}  # nested: {"vmware": {"items": [...], "children": {"esxi": {"items": [...], "children": {}}}}}

for root, dirs, files in os.walk(base):
    dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
    rel = os.path.relpath(root, base)
    if rel == ".":
        segments = ["Fleet"]
    else:
        segments = [p for p in rel.replace(os.sep, "/").split("/")]
    for f in sorted(files):
        if not f.endswith((".yml", ".yaml")) or f.startswith("_"):
            continue
        path = os.path.join(root, f)
        playbook = os.path.relpath(path, base).replace(os.sep, "/")
        try:
            with open(path) as fh: text = fh.read()
            docs = yaml.safe_load(text)
            if not isinstance(docs, list) or len(docs) == 0:
                continue
            play = docs[0]
            if not isinstance(play, dict):
                continue
            is_import = any(k.endswith("import_playbook") for k in play)
        except Exception:
            continue
        blocks = parse_ncs_blocks(text)
        if blocks and len(blocks) > 1:
            # Multi-profile playbook (e.g. run.yml): single tree item with profile selector
            profiles = []
            any_mutating = False
            for blk in blocks:
                lbl = blk.get("label", fallback_label(f, None if is_import else play))
                mut = blk.get("mutating", False)
                if mut:
                    any_mutating = True
                profile = {"label": lbl}
                if mut:
                    profile["mutating"] = True
                op = blk.get("operation")
                if op:
                    profile["operation"] = op
                if blk.get("options"):
                    profile["options"] = blk["options"]
                profiles.append(profile)
            item = build_item(playbook, fallback_label(f, None if is_import else play), any_mutating)
            item["profiles"] = profiles
            add_item(tree, segments, item)
        elif blocks:
            blk = blocks[0]
            lbl = blk.get("label", fallback_label(f, None if is_import else play))
            mut = blk.get("mutating", False)
            opts = blk.get("options", [])
            op = blk.get("operation")
            if op:
                opts = [{"name": "ncs_operation", "label": "Operation", "default": op}] + opts
            add_item(tree, segments, build_item(playbook, lbl, mut, opts))
        else:
            lbl = fallback_label(f, None if is_import else play)
            stem = os.path.splitext(f)[0]
            mut = not any(k in stem for k in READ_ONLY_KEYWORDS)
            opts = fallback_options(play) if not is_import else []
            add_item(tree, segments, build_item(playbook, lbl, mut, opts))

def to_output(tree):
    """Convert nested tree dict to output format with Group/Items/Children."""
    result = []
    for key in sorted(tree.keys()):
        node = tree[key]
        display = NAME_MAP.get(key, key.title())
        entry = {"Group": display, "Items": node["items"]}
        children = to_output(node["children"])
        if children:
            entry["Children"] = children
        if node["items"] or children:
            result.append(entry)
    return result

output = to_output(tree)
# Move Fleet to front if present
fleet = [g for g in output if g["Group"] == "Fleet"]
rest = [g for g in output if g["Group"] != "Fleet"]
print(json.dumps(fleet + rest))
'@
    $command = New-NcsRepoShellCommand -Settings $Settings -Command (
        New-NcsRemoteHeredocCommand -Preamble 'python3' -Content $pyScript -Sentinel 'NCSPLAYBOOKS'
    )
    $probe = Invoke-NcsSshProbe -Settings $Settings -RemoteCommand $command

    if ($probe.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($probe.StdOut)) {
        return @()
    }

    $data = $probe.StdOut | ConvertFrom-Json -AsHashtable
    $groups = [System.Collections.Generic.List[hashtable]]::new()

    foreach ($entry in @($data)) {
        $hasItems = $entry.ContainsKey('Items') -and @($entry['Items']).Length -gt 0
        $hasChildren = $entry.ContainsKey('Children') -and @($entry['Children']).Length -gt 0
        if ($hasItems -or $hasChildren) {
            $groups.Add($entry)
        }
    }

    return $groups
}

function Get-NcsRemoteInventoryTree {
    param(
        [Parameter(Mandatory)]
        [NcsConsoleSettings] $Settings
    )

    $command = New-NcsRepoShellCommand -Settings $Settings -Command "ansible-inventory -i inventory/production --list 2>/dev/null"
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

function Get-NcsRemotePlaybookTags {
    <#
    .SYNOPSIS Fetch declared tags for a playbook via `ansible-playbook --list-tags`.
    .OUTPUTS Group array in the shape Build-NcsTreeView expects, with all tags as
             leaf items under a single "Tags" group. Empty array if the playbook
             declares no tags.
    #>
    param(
        [Parameter(Mandatory)]
        [NcsConsoleSettings] $Settings,
        [Parameter(Mandatory)]
        [string] $Playbook
    )

    $safePlaybook = $Playbook -replace "[^A-Za-z0-9._/-]", ""
    if ([string]::IsNullOrWhiteSpace($safePlaybook)) { return @() }

    $cmd = New-NcsRepoShellCommand -Settings $Settings -Command "ansible-playbook --list-tags '$safePlaybook' 2>&1 | sed -n 's/.*TASK TAGS: \[\(.*\)\]/\1/p' | tr ',' '\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | sort -u"
    $probe = Invoke-NcsSshProbe -Settings $Settings -RemoteCommand $cmd

    if ($probe.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($probe.StdOut)) {
        return @()
    }

    $items = [System.Collections.Generic.List[hashtable]]::new()
    foreach ($line in ($probe.StdOut -split "`n")) {
        $tag = $line.Trim()
        if (-not [string]::IsNullOrWhiteSpace($tag)) {
            $items.Add(@{ Label = $tag; tag = $tag })
        }
    }
    if ($items.Count -eq 0) { return @() }
    return @(@{ Group = "Tags"; Items = $items })
}
