Set-StrictMode -Version Latest

$script:NcsProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Get-NcsConsoleConfigDefaultsPath {
    $moduleRoot = $script:NcsProjectRoot
    return Join-Path -Path $moduleRoot -ChildPath "Config/default-settings.json"
}

function Get-NcsConsoleSettingsDirectory {
    $root = if ($env:APPDATA) {
        $env:APPDATA
    } else {
        Join-Path -Path $HOME -ChildPath ".config"
    }

    return Join-Path -Path $root -ChildPath "NcsConsole"
}

function Get-NcsConsoleSettingsPath {
    return Join-Path -Path (Get-NcsConsoleSettingsDirectory) -ChildPath "settings.json"
}

function Get-NcsConsoleLogDirectory {
    return Join-Path -Path (Get-NcsConsoleSettingsDirectory) -ChildPath "logs"
}

function New-NcsConsoleSettings {
    $settings = [NcsConsoleSettings]::new()
    $settings.LogDirectory = Get-NcsConsoleLogDirectory
    return $settings
}

function ConvertTo-NcsConsoleSettings {
    param(
        [Parameter(Mandatory)]
        [pscustomobject] $InputObject
    )

    $settings = [NcsConsoleSettings]::new()

    foreach ($property in @(
        "SshHost",
        "SshPort",
        "SshUser",
        "SshAuthMode",
        "SshKeyPath",
        "RemoteRepoPath",
        "RemoteReportsPath",
        "SmbShareName",
        "SmbUser",
        "ReportDeliveryMode",
        "AutoRefreshIntervalSeconds",
        "AutoOpenConsoleOnRun",
        "ConsoleDrawerHeight",
        "StrictHostKeyChecking",
        "ConnectTimeoutSeconds",
        "ServerAliveIntervalSeconds",
        "ServerAliveCountMax",
        "LogDirectory",
        "SettingsVersion",
        "LastAction",
        "SettingsColumnWidth",
        "OperateColumnWidth",
        "ReportsColumnWidth",
        "SchedulesColumnWidth",
        "PlaybookTreeColumnWidth",
        "PlaybookPropertiesColumnWidth"
    )) {
        if ($InputObject.PSObject.Properties.Name -contains $property) {
            $settings.$property = $InputObject.$property
        }
    }

    if ($InputObject.PSObject.Properties.Name -contains "ActionState" -and $null -ne $InputObject.ActionState) {
        foreach ($prop in $InputObject.ActionState.PSObject.Properties) {
            $mem = [NcsActionMemory]::new()
            $src = $prop.Value
            if ($null -ne $src) {
                if ($src.PSObject.Properties.Name -contains "Limit") { $mem.Limit = [string] $src.Limit }
                if ($src.PSObject.Properties.Name -contains "Tags")  { $mem.Tags  = [string] $src.Tags  }
                if ($src.PSObject.Properties.Name -contains "Options" -and $null -ne $src.Options) {
                    $opts = @{}
                    foreach ($op in $src.Options.PSObject.Properties) { $opts[$op.Name] = [string] $op.Value }
                    $mem.Options = $opts
                }
                if ($src.PSObject.Properties.Name -contains "UpdatedAt" -and $src.UpdatedAt) {
                    try { $mem.UpdatedAt = [datetime] $src.UpdatedAt } catch { $null = $_ }
                }
            }
            $settings.ActionState[$prop.Name] = $mem
        }
    }

    if ($InputObject.PSObject.Properties.Name -contains "RunHistory" -and $null -ne $InputObject.RunHistory) {
        foreach ($entry in @($InputObject.RunHistory)) {
            if ($null -eq $entry) { continue }
            $e = [NcsRunHistoryEntry]::new()
            foreach ($f in @("ActionId","Label","Playbook","Limit","Tags","State")) {
                if ($entry.PSObject.Properties.Name -contains $f) { $e.$f = [string] $entry.$f }
            }
            if ($entry.PSObject.Properties.Name -contains "ExitCode") { try { $e.ExitCode = [int] $entry.ExitCode } catch { $null = $_ } }
            if ($entry.PSObject.Properties.Name -contains "DurationSeconds") { try { $e.DurationSeconds = [double] $entry.DurationSeconds } catch { $null = $_ } }
            if ($entry.PSObject.Properties.Name -contains "StartedAt" -and $entry.StartedAt) {
                try { $e.StartedAt = [datetime] $entry.StartedAt } catch { $null = $_ }
            }
            if ($entry.PSObject.Properties.Name -contains "Options" -and $null -ne $entry.Options) {
                $opts = @{}
                foreach ($op in $entry.Options.PSObject.Properties) { $opts[$op.Name] = [string] $op.Value }
                $e.Options = $opts
            }
            $settings.RunHistory.Add($e)
        }
    }

    # Apply class defaults for any missing or invalid values from old settings files
    $defaults = [NcsConsoleSettings]::new()
    if (-not $settings.SshPort) { $settings.SshPort = $defaults.SshPort }
    if ([string]::IsNullOrWhiteSpace($settings.SshAuthMode)) { $settings.SshAuthMode = $defaults.SshAuthMode }
    if ([string]::IsNullOrWhiteSpace($settings.RemoteReportsPath)) { $settings.RemoteReportsPath = $defaults.RemoteReportsPath }
    if ([string]::IsNullOrWhiteSpace($settings.SmbShareName)) { $settings.SmbShareName = $defaults.SmbShareName }
    if ($settings.ReportDeliveryMode -notin [NcsReportDeliveryMode].GetEnumNames()) { $settings.ReportDeliveryMode = $defaults.ReportDeliveryMode }
    if ($settings.AutoRefreshIntervalSeconds -lt 0) { $settings.AutoRefreshIntervalSeconds = $defaults.AutoRefreshIntervalSeconds }
    if ($settings.ConsoleDrawerHeight -lt 80) { $settings.ConsoleDrawerHeight = $defaults.ConsoleDrawerHeight }
    if ([string]::IsNullOrWhiteSpace($settings.StrictHostKeyChecking)) { $settings.StrictHostKeyChecking = $defaults.StrictHostKeyChecking }
    if ($settings.ConnectTimeoutSeconds -lt 1) { $settings.ConnectTimeoutSeconds = $defaults.ConnectTimeoutSeconds }
    if ($settings.ServerAliveIntervalSeconds -lt 0) { $settings.ServerAliveIntervalSeconds = $defaults.ServerAliveIntervalSeconds }
    if ($settings.ServerAliveCountMax -lt 1) { $settings.ServerAliveCountMax = $defaults.ServerAliveCountMax }
    if ([string]::IsNullOrWhiteSpace($settings.LogDirectory)) { $settings.LogDirectory = Get-NcsConsoleLogDirectory }
    if ($settings.SettingsVersion -lt $defaults.SettingsVersion) { $settings.SettingsVersion = $defaults.SettingsVersion }

    return $settings
}

function Import-NcsConsoleSettings {
    $path = Get-NcsConsoleSettingsPath
    if (-not (Test-Path -LiteralPath $path)) {
        return New-NcsConsoleSettings
    }

    try {
        $raw = Get-Content -LiteralPath $path -Raw
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return New-NcsConsoleSettings
        }

        $obj = $raw | ConvertFrom-Json
        return ConvertTo-NcsConsoleSettings -InputObject $obj
    } catch {
        Write-Warning "Failed to load settings from '$path': $($_.Exception.Message). Using defaults."
        return New-NcsConsoleSettings
    }
}

function Save-NcsConsoleSettings {
    param(
        [Parameter(Mandatory)]
        [NcsConsoleSettings] $Settings
    )

    $dir = Get-NcsConsoleSettingsDirectory
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }

    $actionState = [ordered]@{}
    if ($null -ne $Settings.ActionState -and $Settings.ActionState.Count -gt 0) {
        $sorted = @($Settings.ActionState.GetEnumerator()) | Sort-Object { $_.Value.UpdatedAt } -Descending | Select-Object -First 50
        foreach ($kv in $sorted) {
            $actionState[$kv.Key] = [ordered]@{
                Limit     = $kv.Value.Limit
                Tags      = $kv.Value.Tags
                Options   = $kv.Value.Options
                UpdatedAt = $kv.Value.UpdatedAt.ToString("o")
            }
        }
    }

    $runHistory = @()
    if ($null -ne $Settings.RunHistory -and $Settings.RunHistory.Count -gt 0) {
        $start = [Math]::Max(0, $Settings.RunHistory.Count - 20)
        for ($i = $start; $i -lt $Settings.RunHistory.Count; $i++) {
            $h = $Settings.RunHistory[$i]
            $runHistory += [ordered]@{
                ActionId        = $h.ActionId
                Label           = $h.Label
                Playbook        = $h.Playbook
                Limit           = $h.Limit
                Tags            = $h.Tags
                Options         = $h.Options
                StartedAt       = $h.StartedAt.ToString("o")
                ExitCode        = $h.ExitCode
                State           = $h.State
                DurationSeconds = $h.DurationSeconds
            }
        }
    }

    $payload = [ordered]@{
        SshHost                  = $Settings.SshHost
        SshPort                  = $Settings.SshPort
        SshUser                  = $Settings.SshUser
        SshAuthMode              = $Settings.SshAuthMode
        SshKeyPath               = $Settings.SshKeyPath
        RemoteRepoPath           = $Settings.RemoteRepoPath
        RemoteReportsPath        = $Settings.RemoteReportsPath
        SmbShareName             = $Settings.SmbShareName
        SmbUser                  = $Settings.SmbUser
        ReportDeliveryMode       = $Settings.ReportDeliveryMode
        AutoRefreshIntervalSeconds = $Settings.AutoRefreshIntervalSeconds
        AutoOpenConsoleOnRun     = $Settings.AutoOpenConsoleOnRun
        ConsoleDrawerHeight      = $Settings.ConsoleDrawerHeight
        StrictHostKeyChecking    = $Settings.StrictHostKeyChecking
        ConnectTimeoutSeconds    = $Settings.ConnectTimeoutSeconds
        ServerAliveIntervalSeconds = $Settings.ServerAliveIntervalSeconds
        ServerAliveCountMax      = $Settings.ServerAliveCountMax
        LogDirectory             = $Settings.LogDirectory
        SettingsVersion          = $Settings.SettingsVersion
        LastAction               = $Settings.LastAction
        SettingsColumnWidth      = $Settings.SettingsColumnWidth
        OperateColumnWidth       = $Settings.OperateColumnWidth
        ReportsColumnWidth       = $Settings.ReportsColumnWidth
        SchedulesColumnWidth     = $Settings.SchedulesColumnWidth
        PlaybookTreeColumnWidth  = $Settings.PlaybookTreeColumnWidth
        PlaybookPropertiesColumnWidth = $Settings.PlaybookPropertiesColumnWidth
        ActionState              = $actionState
        RunHistory               = $runHistory
    } | ConvertTo-Json -Depth 6

    Set-Content -LiteralPath (Get-NcsConsoleSettingsPath) -Value $payload -Encoding UTF8
}
