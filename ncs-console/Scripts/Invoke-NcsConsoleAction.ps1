[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string] $Playbook,
    [string] $Limit = "",
    [string] $ExtraArgs = "",
    [string] $SettingsPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$moduleRoot = Join-Path -Path $projectRoot -ChildPath "Modules"

foreach ($module in @("NcsConsole.Types.ps1", "NcsConsole.Settings.ps1", "NcsConsole.Execution.ps1")) {
    . (Join-Path -Path $moduleRoot -ChildPath $module)
}

$settings = if ([string]::IsNullOrWhiteSpace($SettingsPath)) {
    Import-NcsConsoleSettings
} else {
    ConvertTo-NcsConsoleSettings -InputObject ((Get-Content -LiteralPath $SettingsPath -Raw) | ConvertFrom-Json)
}

$request = [NcsActionRequest]::new($Playbook)
$request.Limit = $Limit
$request.ExtraArgs = $ExtraArgs

$done = $false
$resultRef = $null
$handle = Start-NcsRemoteCommand -Settings $settings -Request $request `
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
