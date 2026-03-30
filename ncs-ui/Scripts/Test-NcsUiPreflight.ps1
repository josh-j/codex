[CmdletBinding()]
param(
    [string] $SettingsPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$moduleRoot = Join-Path -Path $projectRoot -ChildPath "Modules"

Import-Module (Join-Path -Path $moduleRoot -ChildPath "NcsUi.Types.psm1") -Force
Import-Module (Join-Path -Path $moduleRoot -ChildPath "NcsUi.Settings.psm1") -Force
Import-Module (Join-Path -Path $moduleRoot -ChildPath "NcsUi.Execution.psm1") -Force
Import-Module (Join-Path -Path $moduleRoot -ChildPath "NcsUi.Preflight.psm1") -Force

$settings = if ([string]::IsNullOrWhiteSpace($SettingsPath)) {
    Load-NcsUiSettings
} else {
    ConvertTo-NcsUiSettings -InputObject ((Get-Content -LiteralPath $SettingsPath -Raw) | ConvertFrom-Json)
}

$result = Test-NcsRemotePreflight -Settings $settings
$result | ConvertTo-Json -Depth 6
