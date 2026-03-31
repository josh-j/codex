Set-StrictMode -Version Latest

$script:NcsProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Get-NcsUiConfigDefaultsPath {
    $moduleRoot = $script:NcsProjectRoot
    return Join-Path -Path $moduleRoot -ChildPath "Config/default-settings.json"
}

function Get-NcsUiSettingsDirectory {
    $root = if ($env:APPDATA) {
        $env:APPDATA
    } else {
        Join-Path -Path $HOME -ChildPath ".config"
    }

    return Join-Path -Path $root -ChildPath "NcsUi"
}

function Get-NcsUiSettingsPath {
    return Join-Path -Path (Get-NcsUiSettingsDirectory) -ChildPath "settings.json"
}

function New-NcsUiSettings {
    $settings = [NcsUiSettings]::new()
    $defaultsPath = Get-NcsUiConfigDefaultsPath

    if (Test-Path -LiteralPath $defaultsPath) {
        $defaults = Get-Content -LiteralPath $defaultsPath -Raw | ConvertFrom-Json
        $settings = ConvertTo-NcsUiSettings -InputObject $defaults
    }

    return $settings
}

function ConvertTo-NcsUiSettings {
    param(
        [Parameter(Mandatory)]
        [pscustomobject] $InputObject
    )

    $settings = [NcsUiSettings]::new()

    foreach ($property in @("SshHost", "SshPort", "SshUser", "SshAuthMode", "SshKeyPath", "RemoteRepoPath", "RemoteVaultPath", "LastAction")) {
        if ($InputObject.PSObject.Properties.Name -contains $property) {
            $settings.$property = $InputObject.$property
        }
    }

    if (-not $settings.SshPort) {
        $settings.SshPort = 22
    }

    if ([string]::IsNullOrWhiteSpace($settings.LastAction)) {
        $settings.LastAction = ""
    }

    if ([string]::IsNullOrWhiteSpace($settings.SshAuthMode)) {
        $settings.SshAuthMode = [NcsSshAuthMode]::Agent.ToString()
    }

    return $settings
}

function Import-NcsUiSettings {
    $path = Get-NcsUiSettingsPath
    if (-not (Test-Path -LiteralPath $path)) {
        return New-NcsUiSettings
    }

    try {
        $raw = Get-Content -LiteralPath $path -Raw
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return New-NcsUiSettings
        }

        $obj = $raw | ConvertFrom-Json
        return ConvertTo-NcsUiSettings -InputObject $obj
    } catch {
        Write-Warning "Failed to load settings from '$path': $($_.Exception.Message). Using defaults."
        return New-NcsUiSettings
    }
}

function Save-NcsUiSettings {
    param(
        [Parameter(Mandatory)]
        [NcsUiSettings] $Settings
    )

    $dir = Get-NcsUiSettingsDirectory
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }

    $payload = [ordered]@{
        SshHost         = $Settings.SshHost
        SshPort         = $Settings.SshPort
        SshUser         = $Settings.SshUser
        SshAuthMode     = $Settings.SshAuthMode
        SshKeyPath      = $Settings.SshKeyPath
        RemoteRepoPath  = $Settings.RemoteRepoPath
        RemoteVaultPath = $Settings.RemoteVaultPath
        LastAction      = $Settings.LastAction
    } | ConvertTo-Json -Depth 4

    Set-Content -LiteralPath (Get-NcsUiSettingsPath) -Value $payload -Encoding UTF8
}
