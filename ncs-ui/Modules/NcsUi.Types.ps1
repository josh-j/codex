Set-StrictMode -Version Latest

enum NcsUiAction {
    RunAll
    RunSite
    RunHost
    RunVcenter
    DryRun
    Debug
    InventoryPreview
    InventoryHost
    RecentLogs
}

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
    [string] $LastAction = [NcsUiAction]::RunAll.ToString()

    NcsUiSettings() {
    }
}

class NcsActionRequest {
    [NcsUiAction] $Action
    [string] $Site = ""
    [string] $Host = ""
    [string] $ExtraArgs = ""
    [datetime] $RequestedAt = [datetime]::UtcNow

    NcsActionRequest([NcsUiAction] $Action) {
        $this.Action = $Action
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

function Get-NcsUiActionNames {
    [NcsUiAction].GetEnumNames()
}

$script:ActionDisplayMap = [ordered]@{
    "RunAll"           = "Run All"
    "RunSite"          = "Run Site"
    "RunHost"          = "Run Host"
    "RunVcenter"       = "Run vCenter"
    "DryRun"           = "Dry Run"
    "Debug"            = "Debug"
    "InventoryPreview" = "Inventory Preview"
    "InventoryHost"    = "Inventory Host"
    "RecentLogs"       = "Recent Logs"
}

$script:ActionReverseMap = @{}
foreach ($key in $script:ActionDisplayMap.Keys) {
    $script:ActionReverseMap[$script:ActionDisplayMap[$key]] = $key
}

function Get-NcsUiActionDisplayMap {
    return $script:ActionDisplayMap
}

function ConvertTo-NcsActionDisplayName {
    param([string] $EnumName)
    if ($script:ActionDisplayMap.Contains($EnumName)) { return $script:ActionDisplayMap[$EnumName] }
    return $EnumName
}

function ConvertFrom-NcsActionDisplayName {
    param([string] $DisplayName)
    if ($script:ActionReverseMap.ContainsKey($DisplayName)) { return $script:ActionReverseMap[$DisplayName] }
    return $DisplayName
}

function Get-NcsSshAuthModeNames {
    [NcsSshAuthMode].GetEnumNames()
}
