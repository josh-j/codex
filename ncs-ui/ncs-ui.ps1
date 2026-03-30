[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$moduleRoot = Join-Path -Path $projectRoot -ChildPath "Modules"

foreach ($module in @("NcsUi.Types.ps1", "NcsUi.Settings.ps1", "NcsUi.Execution.ps1", "NcsUi.Preflight.ps1", "NcsUi.Wpf.ps1")) {
    . (Join-Path -Path $moduleRoot -ChildPath $module)
}

if (-not $IsWindows) {
    throw "ncs-ui requires Windows because the UI is implemented with WPF."
}

Show-NcsUiApp -ProjectRoot $projectRoot
