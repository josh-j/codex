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
        "StrictHostKeyChecking",
        "ConnectTimeoutSeconds",
        "ServerAliveIntervalSeconds",
        "ServerAliveCountMax",
        "LogDirectory",
        "SettingsVersion",
        "LastAction"
    )) {
        if ($InputObject.PSObject.Properties.Name -contains $property) {
            $settings.$property = $InputObject.$property
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
        StrictHostKeyChecking    = $Settings.StrictHostKeyChecking
        ConnectTimeoutSeconds    = $Settings.ConnectTimeoutSeconds
        ServerAliveIntervalSeconds = $Settings.ServerAliveIntervalSeconds
        ServerAliveCountMax      = $Settings.ServerAliveCountMax
        LogDirectory             = $Settings.LogDirectory
        SettingsVersion          = $Settings.SettingsVersion
        LastAction               = $Settings.LastAction
    } | ConvertTo-Json -Depth 4

    Set-Content -LiteralPath (Get-NcsConsoleSettingsPath) -Value $payload -Encoding UTF8
}
