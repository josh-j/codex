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

# Build the SSH command and run it directly (no WPF dispatcher needed)
$remoteCommand = Get-NcsRemoteShellCommand -Settings $settings -Request $request -RunId ([guid]::NewGuid().ToString("N"))
$arguments = Get-NcsSshArgumentList -Settings $settings -RemoteCommand $remoteCommand
$environment = Get-NcsSshEnvironment -Settings $settings

Write-Host "REMOTE COMMAND: $(Resolve-NcsPlaybookCommand -Settings $settings -Request $request)"

$result = Invoke-NcsToolCommand -FilePath "ssh.exe" -Arguments $arguments -Environment $environment -TimeoutMs 600000

foreach ($line in ($result.StdOut -split "`n")) {
    Write-Host $line
}
if (-not [string]::IsNullOrWhiteSpace($result.StdErr)) {
    foreach ($line in ($result.StdErr -split "`n")) {
        Write-Host $line -ForegroundColor Red
    }
}

exit $result.ExitCode
