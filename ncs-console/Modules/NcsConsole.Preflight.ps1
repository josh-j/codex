Set-StrictMode -Version Latest

function New-NcsPreflightCheck {
    param(
        [Parameter(Mandatory)]
        [string] $Name,
        [Parameter(Mandatory)]
        [bool] $Passed,
        [Parameter(Mandatory)]
        [string] $Message
    )

    return [NcsPreflightCheck]::new($Name, $Passed, $Message)
}

function Invoke-NcsSshProbe {
    param(
        [Parameter(Mandatory)]
        [NcsConsoleSettings] $Settings,
        [Parameter(Mandatory)]
        [string] $RemoteCommand
    )

    $arguments = Get-NcsSshArgumentList -Settings $Settings -RemoteCommand $RemoteCommand
    $environment = $null

    $authMode = $Settings.SshAuthMode
    $askPassSecret = $null
    if ($authMode -eq [NcsSshAuthMode]::Password.ToString() -and -not [string]::IsNullOrWhiteSpace($Settings.SshPassword)) {
        $askPassSecret = $Settings.SshPassword
    } elseif ($authMode -eq [NcsSshAuthMode]::KeyFile.ToString() -and -not [string]::IsNullOrWhiteSpace($Settings.SshKeyPassphrase)) {
        $askPassSecret = $Settings.SshKeyPassphrase
    }
    if ($null -ne $askPassSecret) {
        $environment = New-NcsSshAskPassEnvironment -Secret $askPassSecret
    }

    return Invoke-NcsToolCommand -FilePath "ssh.exe" -Arguments $arguments -Environment $environment
}

function Test-NcsRemotePreflight {
    param(
        [Parameter(Mandatory)]
        [NcsConsoleSettings] $Settings
    )

    $result = [NcsPreflightResult]::new()

    $localChecks = @(
        @{
            Name = "SSH host configured"
            Passed = -not [string]::IsNullOrWhiteSpace($Settings.SshHost)
            Message = if ([string]::IsNullOrWhiteSpace($Settings.SshHost)) { "Enter the remote SSH host." } else { $Settings.SshHost }
        },
        @{
            Name = "SSH user configured"
            Passed = -not [string]::IsNullOrWhiteSpace($Settings.SshUser)
            Message = if ([string]::IsNullOrWhiteSpace($Settings.SshUser)) { "Enter the remote SSH username." } else { $Settings.SshUser }
        },
        @{
            Name = "SSH auth mode configured"
            Passed = -not [string]::IsNullOrWhiteSpace($Settings.SshAuthMode)
            Message = if ([string]::IsNullOrWhiteSpace($Settings.SshAuthMode)) { "Select the SSH authentication mode." } else { $Settings.SshAuthMode }
        },
        @{
            Name = "SSH key path configured"
            Passed = ($Settings.SshAuthMode -ne [NcsSshAuthMode]::KeyFile.ToString()) -or -not [string]::IsNullOrWhiteSpace($Settings.SshKeyPath)
            Message = if (($Settings.SshAuthMode -eq [NcsSshAuthMode]::KeyFile.ToString()) -and [string]::IsNullOrWhiteSpace($Settings.SshKeyPath)) { "Enter the SSH key path for KeyFile authentication." } else { "OK" }
        },
        @{
            Name = "SSH password configured"
            Passed = ($Settings.SshAuthMode -ne [NcsSshAuthMode]::Password.ToString()) -or -not [string]::IsNullOrWhiteSpace($Settings.SshPassword)
            Message = if (($Settings.SshAuthMode -eq [NcsSshAuthMode]::Password.ToString()) -and [string]::IsNullOrWhiteSpace($Settings.SshPassword)) { "Enter the SSH password for Password authentication." } else { "OK" }
        },
        @{
            Name = "Remote repo path configured"
            Passed = -not [string]::IsNullOrWhiteSpace($Settings.RemoteRepoPath)
            Message = if ([string]::IsNullOrWhiteSpace($Settings.RemoteRepoPath)) { "Enter the remote repo path." } else { $Settings.RemoteRepoPath }
        },
        @{
            Name = "Local SSH client"
            Passed = $null -ne (Get-Command -Name "ssh.exe" -ErrorAction SilentlyContinue)
            Message = if ($null -eq (Get-Command -Name "ssh.exe" -ErrorAction SilentlyContinue)) { "OpenSSH client is not available in PATH." } else { "ssh.exe found." }
        }
    )

    foreach ($checkData in $localChecks) {
        $check = New-NcsPreflightCheck -Name $checkData.Name -Passed $checkData.Passed -Message $checkData.Message
        $result.Checks.Add($check)
        if (-not $check.Passed) {
            $result.BlockingIssues.Add($check.Message)
        }
    }

    if ($result.BlockingIssues.Count -gt 0) {
        $result.IsReady = $false
        return $result
    }

    $repo = ConvertTo-NcsRemotePathExpression -Value $Settings.RemoteRepoPath

    $script = @(
        "echo CHECK:ssh:ok"
        "test -d $repo && echo CHECK:repo:ok || echo CHECK:repo:fail"
        "test -d $repo/inventory/production && echo CHECK:inventory:ok || echo CHECK:inventory:fail"
        "(cd $repo && test -f .venv/bin/ansible-playbook && echo CHECK:ansible:ok) || (command -v ansible-playbook >/dev/null 2>&1 && echo CHECK:ansible:ok) || echo CHECK:ansible:fail"
    ) -join "; "

    $checkMeta = [ordered]@{
        ssh        = @{ Name = "SSH connectivity";            FailMsg = "Could not connect to the remote host." }
        repo       = @{ Name = "Repo path exists";            FailMsg = "Remote repo path does not exist." }
        inventory  = @{ Name = "Inventory directory exists";  FailMsg = "Missing inventory/production/ on the remote repo." }
        ansible    = @{ Name = "ansible-playbook available";  FailMsg = "ansible-playbook not found in .venv or PATH." }
    }

    $probe = Invoke-NcsSshProbe -Settings $Settings -RemoteCommand $script

    if ($probe.ExitCode -ne 0 -and [string]::IsNullOrWhiteSpace($probe.StdOut)) {
        $sshMessage = @($probe.StdErr, $probe.StdOut) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -First 1
        if ([string]::IsNullOrWhiteSpace($sshMessage)) { $sshMessage = "SSH connection failed." }
        $check = New-NcsPreflightCheck -Name "SSH connectivity" -Passed $false -Message $sshMessage.Trim()
        $result.Checks.Add($check)
        $result.BlockingIssues.Add("SSH connectivity: $($sshMessage.Trim())")
        $result.IsReady = $false
        return $result
    }

    $checkResults = @{}
    $bannerLines = [System.Collections.Generic.List[string]]::new()
    foreach ($line in ($probe.StdOut -split "`n")) {
        if ($line -match '^CHECK:(\w+):(ok|fail)') {
            $checkResults[$Matches[1]] = $Matches[2] -eq 'ok'
        } elseif (-not [string]::IsNullOrWhiteSpace($line)) {
            $bannerLines.Add($line.TrimEnd())
        }
    }
    if ($null -ne $probe.StdErr) {
        foreach ($line in ($probe.StdErr -split "`n")) {
            if (-not [string]::IsNullOrWhiteSpace($line) -and $line -notmatch '^Warning:' -and $line -notmatch 'passphrase|password' ) {
                $bannerLines.Add($line.TrimEnd())
            }
        }
    }
    $result.Banner = ($bannerLines -join [Environment]::NewLine).Trim()

    foreach ($key in $checkMeta.Keys) {
        $meta = $checkMeta[$key]
        $passed = $checkResults.ContainsKey($key) -and $checkResults[$key]
        $message = if ($passed) { "OK" } else { $meta.FailMsg }
        $check = New-NcsPreflightCheck -Name $meta.Name -Passed $passed -Message $message
        $result.Checks.Add($check)
        if (-not $passed) {
            $result.BlockingIssues.Add("$($meta.Name): $message")
        }
    }

    $result.IsReady = $result.BlockingIssues.Count -eq 0
    return $result
}
