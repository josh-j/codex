Set-StrictMode -Version Latest

$script:MaxOutputLines = 50000

function ConvertTo-NcsBashLiteral {
    param(
        [Parameter(Mandatory)]
        [string] $Value
    )

    $sq = [char]39
    $dq = [char]34
    $escaped = $Value -replace "$sq", "$sq$dq$sq$dq$sq"
    return "$sq$escaped$sq"
}

function ConvertTo-NcsRemotePathExpression {
    param(
        [Parameter(Mandatory)]
        [string] $Value
    )

    if ($Value -eq "~") {
        return '$HOME'
    }

    if ($Value.StartsWith("~/")) {
        $suffix = $Value.Substring(2)
        if ([string]::IsNullOrWhiteSpace($suffix)) {
            return '$HOME'
        }

        return '$HOME/' + (ConvertTo-NcsBashLiteral -Value $suffix)
    }

    return ConvertTo-NcsBashLiteral -Value $Value
}

function Split-NcsExtraArgs {
    param(
        [string] $ExtraArgs
    )

    if ([string]::IsNullOrWhiteSpace($ExtraArgs)) {
        return @()
    }

    return [System.Management.Automation.PSParser]::Tokenize($ExtraArgs, [ref] $null) |
        Where-Object { $_.Type -in @("String", "CommandArgument") } |
        ForEach-Object { $_.Content }
}

function Invoke-NcsToolCommand {
    param(
        [Parameter(Mandatory)]
        [string] $FilePath,
        [Parameter(Mandatory)]
        [string[]] $Arguments,
        [hashtable] $Environment,
        [int] $TimeoutMs = 30000
    )

    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $FilePath
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false

    foreach ($argument in $Arguments) {
        $psi.ArgumentList.Add($argument)
    }

    if ($Environment) {
        foreach ($key in $Environment.Keys) {
            $psi.Environment[$key] = [string] $Environment[$key]
        }
    }

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $psi

    try {
        [void] $process.Start()
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()

        $exited = $process.WaitForExit($TimeoutMs)
        if (-not $exited) {
            $process.Kill($true)
            throw "Process '$FilePath' timed out after $($TimeoutMs / 1000) seconds."
        }

        $process.WaitForExit()

        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            StdOut   = $stdoutTask.GetAwaiter().GetResult()
            StdErr   = $stderrTask.GetAwaiter().GetResult()
        }
    } finally {
        $process.Dispose()
    }
}

function Get-NcsSshTarget {
    param(
        [Parameter(Mandatory)]
        [NcsUiSettings] $Settings
    )

    return "{0}@{1}" -f $Settings.SshUser, $Settings.SshHost
}

function New-NcsSshPasswordEnvironment {
    param(
        [Parameter(Mandatory)]
        [NcsUiSettings] $Settings
    )

    if ([string]::IsNullOrWhiteSpace($Settings.SshPassword)) {
        throw "Password authentication requires an SSH password."
    }

    $moduleRoot = Split-Path -Parent $PSScriptRoot
    $askPassScript = Join-Path -Path $moduleRoot -ChildPath "Scripts/askpass.cmd"
    return @{
        SSH_ASKPASS         = $askPassScript
        SSH_ASKPASS_REQUIRE = "force"
        NCS_UI_PASS         = $Settings.SshPassword
        DISPLAY             = "ncs-ui"
    }
}

function Get-NcsSshArgumentList {
    param(
        [Parameter(Mandatory)]
        [NcsUiSettings] $Settings,
        [Parameter(Mandatory)]
        [string] $RemoteCommand
    )

    $arguments = [System.Collections.Generic.List[string]]::new()
    $arguments.Add("-p")
    $arguments.Add([string] $Settings.SshPort)
    $arguments.Add("-o")
    $arguments.Add("BatchMode=no")

    $authMode = [System.Enum]::Parse([NcsSshAuthMode], $Settings.SshAuthMode)
    switch ($authMode) {
        ([NcsSshAuthMode]::Agent) {
            $arguments.Add("-o")
            $arguments.Add("PreferredAuthentications=publickey")
        }
        ([NcsSshAuthMode]::KeyFile) {
            if ([string]::IsNullOrWhiteSpace($Settings.SshKeyPath)) {
                throw "KeyFile authentication requires an SSH key path."
            }

            $arguments.Add("-i")
            $arguments.Add($Settings.SshKeyPath)
            $arguments.Add("-o")
            $arguments.Add("IdentitiesOnly=yes")
        }
        ([NcsSshAuthMode]::Password) {
            $arguments.Add("-o")
            $arguments.Add("PreferredAuthentications=password,keyboard-interactive")
            $arguments.Add("-o")
            $arguments.Add("PubkeyAuthentication=no")
        }
    }

    $arguments.Add((Get-NcsSshTarget -Settings $Settings))
    $arguments.Add($RemoteCommand)
    return $arguments
}

function Get-NcsMakeCommand {
    param(
        [Parameter(Mandatory)]
        [NcsActionRequest] $Request
    )

    switch ($Request.Action) {
        ([NcsUiAction]::RunAll) { return "make run" }
        ([NcsUiAction]::RunSite) {
            if ([string]::IsNullOrWhiteSpace($Request.Site)) {
                throw "Run Site requires a site value."
            }

            return "make run-site SITE={0}" -f (ConvertTo-NcsBashLiteral -Value $Request.Site)
        }
        ([NcsUiAction]::RunHost) {
            if ([string]::IsNullOrWhiteSpace($Request.Host)) {
                throw "Run Host requires an Ansible host value."
            }

            return "ansible-playbook -i inventory/production/hosts.yml playbooks/ops_checks.yml --limit {0},localhost --vault-password-file .vaultpass" -f (ConvertTo-NcsBashLiteral -Value $Request.Host)
        }
        ([NcsUiAction]::RunVcenter) { return "make run-vcenter" }
        ([NcsUiAction]::DryRun) { return "make dry-run" }
        ([NcsUiAction]::Debug) { return "make debug" }
        ([NcsUiAction]::InventoryPreview) { return "make inventory" }
        ([NcsUiAction]::InventoryHost) {
            if ([string]::IsNullOrWhiteSpace($Request.Host)) {
                throw "Inventory Host requires an Ansible host value."
            }

            return "make inventory-host HOST={0}" -f (ConvertTo-NcsBashLiteral -Value $Request.Host)
        }
        ([NcsUiAction]::RecentLogs) { return "make logs-recent" }
        default { throw "Unsupported action: $($Request.Action)" }
    }
}

function Get-NcsDirectCommand {
    param(
        [Parameter(Mandatory)]
        [NcsUiSettings] $Settings,
        [Parameter(Mandatory)]
        [NcsActionRequest] $Request
    )

    $inventory = "inventory/production/hosts.yml"
    $vault = ConvertTo-NcsRemotePathExpression -Value $Settings.RemoteVaultPath

    switch ($Request.Action) {
        ([NcsUiAction]::RunAll) {
            return "ansible-playbook -i $inventory playbooks/ops_checks.yml --vault-password-file $vault"
        }
        ([NcsUiAction]::RunSite) {
            if ([string]::IsNullOrWhiteSpace($Request.Site)) {
                throw "Run Site requires a site value."
            }

            $site = ConvertTo-NcsBashLiteral -Value $Request.Site
            return "ansible-playbook -i $inventory playbooks/ops_checks.yml --limit ${site},localhost --vault-password-file $vault"
        }
        ([NcsUiAction]::RunHost) {
            if ([string]::IsNullOrWhiteSpace($Request.Host)) {
                throw "Run Host requires an Ansible host value."
            }

            $host = ConvertTo-NcsBashLiteral -Value $Request.Host
            return "ansible-playbook -i $inventory playbooks/ops_checks.yml --limit ${host},localhost --vault-password-file $vault"
        }
        ([NcsUiAction]::RunVcenter) {
            return "ansible-playbook -i $inventory playbooks/ops_checks.yml --limit vcenters,localhost --tags vcenter --vault-password-file $vault"
        }
        ([NcsUiAction]::DryRun) {
            return "ansible-playbook -i $inventory playbooks/ops_checks.yml --check --diff --vault-password-file $vault"
        }
        ([NcsUiAction]::Debug) {
            return "ansible-playbook -i $inventory playbooks/ops_checks.yml -vvv --vault-password-file $vault"
        }
        default {
            return Get-NcsMakeCommand -Request $Request
        }
    }
}

function Resolve-NcsActionCommand {
    param(
        [Parameter(Mandatory)]
        [NcsUiSettings] $Settings,
        [Parameter(Mandatory)]
        [NcsActionRequest] $Request
    )

    $defaultVault = ".vaultpass"
    $command = if ($Settings.RemoteVaultPath -eq $defaultVault -or $Request.Action -in @([NcsUiAction]::InventoryPreview, [NcsUiAction]::InventoryHost, [NcsUiAction]::RecentLogs)) {
        Get-NcsMakeCommand -Request $Request
    } else {
        Get-NcsDirectCommand -Settings $Settings -Request $Request
    }

    $extraArgs = Split-NcsExtraArgs -ExtraArgs $Request.ExtraArgs
    if ($extraArgs.Count -gt 0) {
        $escapedArgs = $extraArgs | ForEach-Object { ConvertTo-NcsBashLiteral -Value $_ }
        $command = "{0} {1}" -f $command, ($escapedArgs -join " ")
    }

    return $command
}

function Get-NcsRemoteShellCommand {
    param(
        [Parameter(Mandatory)]
        [NcsUiSettings] $Settings,
        [Parameter(Mandatory)]
        [NcsActionRequest] $Request
    )

    $repo = ConvertTo-NcsRemotePathExpression -Value $Settings.RemoteRepoPath
    $actionCommand = Resolve-NcsActionCommand -Settings $Settings -Request $Request
    return "cd $repo && $actionCommand"
}

function Find-NcsDetectedPaths {
    param(
        [string[]] $Lines
    )

    $matches = foreach ($line in $Lines) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }

        foreach ($match in [regex]::Matches($line, "((/|~)[\w\.\-\/]+)")) {
            $match.Value
        }
    }

    return $matches | Sort-Object -Unique
}

function Start-NcsRemoteCommand {
    param(
        [Parameter(Mandatory)]
        [NcsUiSettings] $Settings,
        [Parameter(Mandatory)]
        [NcsActionRequest] $Request,
        [scriptblock] $OnOutput,
        [scriptblock] $OnCompleted
    )

    $remoteCommand = Get-NcsRemoteShellCommand -Settings $Settings -Request $Request

    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = "ssh.exe"
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    foreach ($argument in (Get-NcsSshArgumentList -Settings $Settings -RemoteCommand $remoteCommand)) {
        $psi.ArgumentList.Add($argument)
    }

    if ($Settings.SshAuthMode -eq [NcsSshAuthMode]::Password.ToString()) {
        $passEnv = New-NcsSshPasswordEnvironment -Settings $Settings
        foreach ($key in $passEnv.Keys) {
            $psi.Environment[$key] = $passEnv[$key]
        }
    }

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $psi
    $lines = [System.Collections.Generic.List[string]]::new()
    $startedAt = Get-Date

    $outputHandler = [System.Diagnostics.DataReceivedEventHandler]{
        param($sender, $eventArgs)
        if ($null -eq $eventArgs.Data) {
            return
        }

        $timestamped = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $eventArgs.Data
        $lines.Add($timestamped)
        if ($OnOutput) {
            & $OnOutput $timestamped
        }
    }

    $completedHandler = [System.EventHandler]{
        param($sender, $eventArgs)
        $process.WaitForExit()
        if ($lines.Count -gt $script:MaxOutputLines) {
            $lines.RemoveRange(0, $lines.Count - $script:MaxOutputLines)
        }
        $result = [NcsRunResult]::new()
        $result.Action = $Request.Action.ToString()
        $result.Command = $remoteCommand
        $result.ExitCode = $process.ExitCode
        $result.Succeeded = $process.ExitCode -eq 0
        $result.StartedAt = $startedAt
        $result.EndedAt = Get-Date
        $result.Duration = $result.EndedAt.Value - $startedAt
        $result.OutputLines = $lines.ToArray()
        $result.DetectedPaths = Find-NcsDetectedPaths -Lines $result.OutputLines

        $process.remove_OutputDataReceived($outputHandler)
        $process.remove_ErrorDataReceived($outputHandler)
        $process.remove_Exited($completedHandler)
        $process.Dispose()

        if ($OnCompleted) {
            & $OnCompleted $result
        }
    }

    $process.EnableRaisingEvents = $true
    $process.add_OutputDataReceived($outputHandler)
    $process.add_ErrorDataReceived($outputHandler)
    $process.add_Exited($completedHandler)

    try {
        [void] $process.Start()
        $process.BeginOutputReadLine()
        $process.BeginErrorReadLine()
    } catch {
        $process.Dispose()
        throw
    }

    return [pscustomobject]@{
        Process       = $process
        RemoteCommand = $remoteCommand
        StartedAt     = $startedAt
    }
}

function Stop-NcsRemoteCommand {
    param(
        [Parameter(Mandatory)]
        $Handle
    )

    if ($Handle.Process -and -not $Handle.Process.HasExited) {
        $Handle.Process.Kill($true)
    }
}

function Invoke-NcsAction {
    param(
        [Parameter(Mandatory)]
        [NcsUiSettings] $Settings,
        [Parameter(Mandatory)]
        [NcsActionRequest] $Request,
        [scriptblock] $OnOutput,
        [scriptblock] $OnCompleted
    )

    return Start-NcsRemoteCommand -Settings $Settings -Request $Request -OnOutput $OnOutput -OnCompleted $OnCompleted
}

function Invoke-NcsRunAll {
    param([NcsUiSettings] $Settings, [string] $ExtraArgs, [scriptblock] $OnOutput, [scriptblock] $OnCompleted)
    $request = [NcsActionRequest]::new([NcsUiAction]::RunAll)
    $request.ExtraArgs = $ExtraArgs
    Invoke-NcsAction -Settings $Settings -Request $request -OnOutput $OnOutput -OnCompleted $OnCompleted
}

function Invoke-NcsRunSite {
    param([NcsUiSettings] $Settings, [string] $Site, [string] $ExtraArgs, [scriptblock] $OnOutput, [scriptblock] $OnCompleted)
    $request = [NcsActionRequest]::new([NcsUiAction]::RunSite)
    $request.Site = $Site
    $request.ExtraArgs = $ExtraArgs
    Invoke-NcsAction -Settings $Settings -Request $request -OnOutput $OnOutput -OnCompleted $OnCompleted
}

function Invoke-NcsRunHost {
    param([NcsUiSettings] $Settings, [string] $AnsibleHost, [string] $ExtraArgs, [scriptblock] $OnOutput, [scriptblock] $OnCompleted)
    $request = [NcsActionRequest]::new([NcsUiAction]::RunHost)
    $request.Host = $AnsibleHost
    $request.ExtraArgs = $ExtraArgs
    Invoke-NcsAction -Settings $Settings -Request $request -OnOutput $OnOutput -OnCompleted $OnCompleted
}

function Invoke-NcsRunVcenter {
    param([NcsUiSettings] $Settings, [string] $ExtraArgs, [scriptblock] $OnOutput, [scriptblock] $OnCompleted)
    $request = [NcsActionRequest]::new([NcsUiAction]::RunVcenter)
    $request.ExtraArgs = $ExtraArgs
    Invoke-NcsAction -Settings $Settings -Request $request -OnOutput $OnOutput -OnCompleted $OnCompleted
}

function Invoke-NcsDryRun {
    param([NcsUiSettings] $Settings, [string] $ExtraArgs, [scriptblock] $OnOutput, [scriptblock] $OnCompleted)
    $request = [NcsActionRequest]::new([NcsUiAction]::DryRun)
    $request.ExtraArgs = $ExtraArgs
    Invoke-NcsAction -Settings $Settings -Request $request -OnOutput $OnOutput -OnCompleted $OnCompleted
}

function Invoke-NcsDebug {
    param([NcsUiSettings] $Settings, [string] $ExtraArgs, [scriptblock] $OnOutput, [scriptblock] $OnCompleted)
    $request = [NcsActionRequest]::new([NcsUiAction]::Debug)
    $request.ExtraArgs = $ExtraArgs
    Invoke-NcsAction -Settings $Settings -Request $request -OnOutput $OnOutput -OnCompleted $OnCompleted
}

function Invoke-NcsInventoryPreview {
    param([NcsUiSettings] $Settings, [string] $ExtraArgs, [scriptblock] $OnOutput, [scriptblock] $OnCompleted)
    $request = [NcsActionRequest]::new([NcsUiAction]::InventoryPreview)
    $request.ExtraArgs = $ExtraArgs
    Invoke-NcsAction -Settings $Settings -Request $request -OnOutput $OnOutput -OnCompleted $OnCompleted
}

function Invoke-NcsInventoryHost {
    param([NcsUiSettings] $Settings, [string] $AnsibleHost, [string] $ExtraArgs, [scriptblock] $OnOutput, [scriptblock] $OnCompleted)
    $request = [NcsActionRequest]::new([NcsUiAction]::InventoryHost)
    $request.Host = $AnsibleHost
    $request.ExtraArgs = $ExtraArgs
    Invoke-NcsAction -Settings $Settings -Request $request -OnOutput $OnOutput -OnCompleted $OnCompleted
}

function Invoke-NcsRecentLogs {
    param([NcsUiSettings] $Settings, [string] $ExtraArgs, [scriptblock] $OnOutput, [scriptblock] $OnCompleted)
    $request = [NcsActionRequest]::new([NcsUiAction]::RecentLogs)
    $request.ExtraArgs = $ExtraArgs
    Invoke-NcsAction -Settings $Settings -Request $request -OnOutput $OnOutput -OnCompleted $OnCompleted
}

Export-ModuleMember -Function ConvertTo-NcsBashLiteral, ConvertTo-NcsRemotePathExpression, Get-NcsSshArgumentList, Invoke-NcsToolCommand, New-NcsSshPasswordEnvironment, Resolve-NcsActionCommand, Get-NcsRemoteShellCommand, Start-NcsRemoteCommand, Stop-NcsRemoteCommand, Invoke-NcsAction, Invoke-NcsRunAll, Invoke-NcsRunSite, Invoke-NcsRunHost, Invoke-NcsRunVcenter, Invoke-NcsDryRun, Invoke-NcsDebug, Invoke-NcsInventoryPreview, Invoke-NcsInventoryHost, Invoke-NcsRecentLogs
