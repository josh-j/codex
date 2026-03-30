[CmdletBinding()]
param(
    [string] $SettingsPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$moduleRoot = Join-Path -Path $projectRoot -ChildPath "Modules"

foreach ($module in @("NcsUi.Types.ps1", "NcsUi.Settings.ps1", "NcsUi.Execution.ps1", "NcsUi.Preflight.ps1")) {
    . (Join-Path -Path $moduleRoot -ChildPath $module)
}

$settings = if ([string]::IsNullOrWhiteSpace($SettingsPath)) {
    Import-NcsUiSettings
} else {
    ConvertTo-NcsUiSettings -InputObject ((Get-Content -LiteralPath $SettingsPath -Raw) | ConvertFrom-Json)
}

$result = Test-NcsRemotePreflight -Settings $settings
$result | ConvertTo-Json -Depth 6
