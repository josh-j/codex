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
    [string] $Filter = ""
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
            $currentOption[$Matches[1].Trim()] = $Matches[2].Trim()
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

