[CmdletBinding()]
param(
    [string] $SettingsPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$moduleRoot = Join-Path -Path $projectRoot -ChildPath "Modules"

foreach ($module in @("NcsConsole.Types.ps1", "NcsConsole.Settings.ps1", "NcsConsole.Execution.ps1", "NcsConsole.Preflight.ps1")) {
    . (Join-Path -Path $moduleRoot -ChildPath $module)
}

$settings = if ([string]::IsNullOrWhiteSpace($SettingsPath)) {
    Import-NcsConsoleSettings
} else {
    ConvertTo-NcsConsoleSettings -InputObject ((Get-Content -LiteralPath $SettingsPath -Raw) | ConvertFrom-Json)
}

$result = Test-NcsRemotePreflight -Settings $settings
$result | ConvertTo-Json -Depth 6
