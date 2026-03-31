[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$moduleRoot = Join-Path -Path $projectRoot -ChildPath "Modules"

foreach ($module in @("NcsConsole.Types.ps1", "NcsConsole.Settings.ps1", "NcsConsole.Execution.ps1", "NcsConsole.Preflight.ps1", "NcsConsole.Wpf.ps1")) {
    . (Join-Path -Path $moduleRoot -ChildPath $module)
}

if (-not $IsWindows) {
    throw "ncs-console requires Windows because the UI is implemented with WPF."
}

Show-NcsConsoleApp -ProjectRoot $projectRoot
