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
        [NcsUiSettings] $Settings,
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
        [NcsUiSettings] $Settings
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
            Name = "Remote vault path configured"
            Passed = -not [string]::IsNullOrWhiteSpace($Settings.RemoteVaultPath)
            Message = if ([string]::IsNullOrWhiteSpace($Settings.RemoteVaultPath)) { "Enter the remote vault path." } else { $Settings.RemoteVaultPath }
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
    $vault = ConvertTo-NcsRemotePathExpression -Value $Settings.RemoteVaultPath

    $script = @(
        "echo CHECK:ssh:ok"
        "test -d $repo && echo CHECK:repo:ok || echo CHECK:repo:fail"
        "test -f $repo/Makefile && echo CHECK:makefile:ok || echo CHECK:makefile:fail"
        "test -f $repo/inventory/production/hosts.yml && echo CHECK:inventory:ok || echo CHECK:inventory:fail"
        "(cd $repo && test -f $vault) && echo CHECK:vault:ok || echo CHECK:vault:fail"
        "command -v make >/dev/null 2>&1 && echo CHECK:make:ok || echo CHECK:make:fail"
        "command -v ansible-playbook >/dev/null 2>&1 && echo CHECK:ansible:ok || echo CHECK:ansible:fail"
        "command -v ansible-inventory >/dev/null 2>&1 && echo CHECK:ainventory:ok || echo CHECK:ainventory:fail"
    ) -join "; "

    $checkMeta = [ordered]@{
        ssh        = @{ Name = "SSH connectivity";            FailMsg = "Could not connect to the remote host." }
        repo       = @{ Name = "Repo path exists";            FailMsg = "Remote repo path does not exist." }
        makefile   = @{ Name = "Makefile exists";             FailMsg = "No Makefile found in the remote repo." }
        inventory  = @{ Name = "Inventory file exists";       FailMsg = "Missing inventory/production/hosts.yml on the remote repo." }
        vault      = @{ Name = "Vault file exists";           FailMsg = "Configured vault file was not found on the remote repo." }
        make       = @{ Name = "make available";              FailMsg = "make command not found on the remote host." }
        ansible    = @{ Name = "ansible-playbook available";  FailMsg = "ansible-playbook command not found on the remote host." }
        ainventory = @{ Name = "ansible-inventory available"; FailMsg = "ansible-inventory command not found on the remote host." }
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
    foreach ($line in ($probe.StdOut -split "`n")) {
        if ($line -match '^CHECK:(\w+):(ok|fail)') {
            $checkResults[$Matches[1]] = $Matches[2] -eq 'ok'
        }
    }

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
