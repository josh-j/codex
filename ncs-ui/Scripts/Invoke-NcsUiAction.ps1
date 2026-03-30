[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet("RunAll", "RunSite", "RunHost", "RunVcenter", "DryRun", "Debug", "InventoryPreview", "InventoryHost", "RecentLogs")]
    [string] $Action,
    [string] $Site = "",
    [string] $AnsibleHost = "",
    [string] $ExtraArgs = "",
    [string] $SettingsPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$moduleRoot = Join-Path -Path $projectRoot -ChildPath "Modules"

Import-Module (Join-Path -Path $moduleRoot -ChildPath "NcsUi.Types.psm1") -Force
Import-Module (Join-Path -Path $moduleRoot -ChildPath "NcsUi.Settings.psm1") -Force
Import-Module (Join-Path -Path $moduleRoot -ChildPath "NcsUi.Execution.psm1") -Force

$settings = if ([string]::IsNullOrWhiteSpace($SettingsPath)) {
    Import-NcsUiSettings
} else {
    ConvertTo-NcsUiSettings -InputObject ((Get-Content -LiteralPath $SettingsPath -Raw) | ConvertFrom-Json)
}

$request = [NcsActionRequest]::new([System.Enum]::Parse([NcsUiAction], $Action))
$request.Site = $Site
$request.Host = $AnsibleHost
$request.ExtraArgs = $ExtraArgs

$done = $false
$resultRef = $null
$handle = Invoke-NcsAction -Settings $settings -Request $request `
    -OnOutput {
        param($line)
        Write-Host $line
    } `
    -OnCompleted {
        param($runResult)
        $script:done = $true
        $script:resultRef = $runResult
    }

Write-Host "REMOTE COMMAND: $($handle.RemoteCommand)"

while (-not $done) {
    Start-Sleep -Milliseconds 200
}

$resultRef | ConvertTo-Json -Depth 6
