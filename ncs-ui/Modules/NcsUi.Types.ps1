Set-StrictMode -Version Latest

enum NcsSshAuthMode {
    Agent
    KeyFile
    Password
}

class NcsUiSettings {
    [string] $SshHost = ""
    [int] $SshPort = 22
    [string] $SshUser = ""
    [string] $SshAuthMode = [NcsSshAuthMode]::Agent.ToString()
    [string] $SshKeyPath = ""
    [string] $SshPassword = ""
    [string] $RemoteRepoPath = "~/ansible-ncs"
    [string] $RemoteVaultPath = ".vaultpass"
    [string] $DefaultSite = ""
    [string] $DefaultAnsibleHost = ""
    [string] $LastAction = ""

    NcsUiSettings() {
    }
}

class NcsActionRequest {
    [string] $Playbook
    [string] $Site = ""
    [string] $Host = ""
    [string] $ExtraArgs = ""
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
        return "{0} {1} - {2}" -f $prefix, $this.Name, $this.Message
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

    foreach ($line in $lines) {
        if ([string]::IsNullOrWhiteSpace($line) -or $line -match '^\s*#') { continue }

        if ($line -match '^- group:\s*(.+)$') {
            $currentGroup = @{ Group = $Matches[1].Trim(); Items = [System.Collections.Generic.List[hashtable]]::new() }
            $groups.Add($currentGroup)
            $currentItem = $null
            continue
        }

        if ($line -match '^\s+- label:\s*(.+)$' -and $null -ne $currentGroup) {
            $currentItem = @{ Label = $Matches[1].Trim() }
            $currentGroup.Items.Add($currentItem)
            continue
        }

        if ($line -match '^\s+(\w+):\s*(.+)$' -and $null -ne $currentItem) {
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
