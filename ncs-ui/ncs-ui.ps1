[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$moduleRoot = Join-Path -Path $projectRoot -ChildPath "Modules"

$modules = @(
    "NcsUi.Types.psm1",
    "NcsUi.Settings.psm1",
    "NcsUi.Execution.psm1",
    "NcsUi.Preflight.psm1",
    "NcsUi.Wpf.psm1"
)

foreach ($module in $modules) {
    Import-Module (Join-Path -Path $moduleRoot -ChildPath $module) -Force
}

if (-not $IsWindows) {
    throw "ncs-ui requires Windows because the UI is implemented with WPF."
}

Show-NcsUiApp -ProjectRoot $projectRoot
