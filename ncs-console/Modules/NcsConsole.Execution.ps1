Set-StrictMode -Version Latest

$script:NcsProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$script:MaxOutputLines = 50000
$script:NcsActiveExecutionState = $null

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
    $psi.RedirectStandardInput = $true
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
        if ($Environment -and $Environment.ContainsKey('NCS_UI_PASS')) {
            $process.StandardInput.WriteLine($Environment['NCS_UI_PASS'])
        } else {
            $process.StandardInput.WriteLine("")
        }
        $process.StandardInput.Close()
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
        [NcsConsoleSettings] $Settings
    )

    return "{0}@{1}" -f $Settings.SshUser, $Settings.SshHost
}

function New-NcsSshAskPassEnvironment {
    param(
        [Parameter(Mandatory)]
        [string] $Secret
    )

    $askPassScript = Join-Path -Path $script:NcsProjectRoot -ChildPath "Scripts/askpass.cmd"
    return @{
        SSH_ASKPASS         = $askPassScript
        SSH_ASKPASS_REQUIRE = "force"
        NCS_UI_PASS         = $Secret
        DISPLAY             = "ncs-console"
    }
}

function Get-NcsSshArgumentList {
    param(
        [Parameter(Mandatory)]
        [NcsConsoleSettings] $Settings,
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

function Resolve-NcsPlaybookCommand {
    param(
        [Parameter(Mandatory)]
        [NcsConsoleSettings] $Settings,
        [Parameter(Mandatory)]
        [NcsActionRequest] $Request
    )

    $inventory = "inventory/production"
    $command = "ansible-playbook -i $inventory playbooks/$($Request.Playbook) --vault-password-file .vaultpass"

    if (-not [string]::IsNullOrWhiteSpace($Request.Limit)) {
        $command += " --limit " + (ConvertTo-NcsBashLiteral -Value $Request.Limit)
    }

    if (-not [string]::IsNullOrWhiteSpace($Request.Tags)) {
        $command += " --tags " + (ConvertTo-NcsBashLiteral -Value $Request.Tags)
    }

    if ($Request.CheckMode) { $command += " --check" }
    if ($Request.Diff) { $command += " --diff" }

    if (-not [string]::IsNullOrWhiteSpace($Request.Verbosity) -and $Request.Verbosity -ne "Normal") {
        $command += " $($Request.Verbosity)"
    }

    if ($Request.Options.Count -gt 0) {
        foreach ($key in $Request.Options.Keys) {
            $command += " -e " + (ConvertTo-NcsBashLiteral -Value "$key=$($Request.Options[$key])")
        }
    }

    $extraArgs = Split-NcsExtraArgs -ExtraArgs $Request.ExtraArgs
    if (@($extraArgs).Length -gt 0) {
        $escapedArgs = $extraArgs | ForEach-Object { ConvertTo-NcsBashLiteral -Value $_ }
        $command += " " + ($escapedArgs -join " ")
    }

    return $command
}

function Get-NcsRemoteShellCommand {
    param(
        [Parameter(Mandatory)]
        [NcsConsoleSettings] $Settings,
        [Parameter(Mandatory)]
        [NcsActionRequest] $Request
    )

    $repo = ConvertTo-NcsRemotePathExpression -Value $Settings.RemoteRepoPath
    $actionCommand = Resolve-NcsPlaybookCommand -Settings $Settings -Request $Request
    return "cd $repo && if [ -f .venv/bin/activate ]; then . .venv/bin/activate; fi && $actionCommand"
}

function Find-NcsDetectedPaths {
    param(
        [string[]] $Lines
    )

    $pathMatches = foreach ($line in $Lines) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }

        foreach ($match in [regex]::Matches($line, "((/|~)[\w\.\-\/]+)")) {
            $match.Value
        }
    }

    return $pathMatches | Sort-Object -Unique
}

function Start-NcsRemoteCommand {
    param(
        [Parameter(Mandatory)]
        [NcsConsoleSettings] $Settings,
        [Parameter(Mandatory)]
        [NcsActionRequest] $Request,
        [scriptblock] $OnOutput,
        [scriptblock] $OnCompleted
    )

    $remoteCommand = Get-NcsRemoteShellCommand -Settings $Settings -Request $Request

    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = "ssh.exe"
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    foreach ($argument in (Get-NcsSshArgumentList -Settings $Settings -RemoteCommand $remoteCommand)) {
        $psi.ArgumentList.Add($argument)
    }

    $authMode = $Settings.SshAuthMode
    $askPassSecret = $null
    if ($authMode -eq [NcsSshAuthMode]::Password.ToString() -and -not [string]::IsNullOrWhiteSpace($Settings.SshPassword)) {
        $askPassSecret = $Settings.SshPassword
    } elseif ($authMode -eq [NcsSshAuthMode]::KeyFile.ToString() -and -not [string]::IsNullOrWhiteSpace($Settings.SshKeyPassphrase)) {
        $askPassSecret = $Settings.SshKeyPassphrase
    }
    if ($null -ne $askPassSecret) {
        $askEnv = New-NcsSshAskPassEnvironment -Secret $askPassSecret
        foreach ($key in $askEnv.Keys) {
            $psi.Environment[$key] = $askEnv[$key]
        }
    }

    $executionState = [pscustomobject]@{
        Process      = [System.Diagnostics.Process]::new()
        Lines        = [System.Collections.Generic.List[string]]::new()
        PendingLines = [System.Collections.Concurrent.ConcurrentQueue[string]]::new()
        StartedAt    = Get-Date
        StdoutState  = [pscustomobject]@{
            Reader = $null
            Task   = $null
            Closed = $false
        }
        StderrState  = [pscustomobject]@{
            Reader = $null
            Task   = $null
            Closed = $false
        }
        DrainTimer   = [System.Windows.Threading.DispatcherTimer]::new()
    }
    $executionState.Process.StartInfo = $psi

    $startRead = {
        param($state)
        if (-not $state.Closed -and $null -eq $state.Task) {
            $state.Task = $state.Reader.ReadLineAsync()
        }
    }

    $drainRead = {
        param($state)
        while ($null -ne $state.Task -and $state.Task.IsCompleted) {
            $lineText = $state.Task.GetAwaiter().GetResult()
            $state.Task = $null

            if ($null -eq $lineText) {
                $state.Closed = $true
                break
            }

            $timestamped = "[{0}] {1}" -f ([System.DateTime]::Now.ToString("HH:mm:ss")), $lineText
            $script:NcsActiveExecutionState.Lines.Add($timestamped)
            $script:NcsActiveExecutionState.PendingLines.Enqueue($timestamped)
            & $startRead $state
        }
    }

    $executionState.DrainTimer.Interval = [System.TimeSpan]::FromMilliseconds(100)
    $tickHandler = {
        param($sender, $eventArgs)
        try {
            $state = $script:NcsActiveExecutionState
            if ($null -eq $state) {
                $sender.Stop()
                return
            }

            & $drainRead $state.StdoutState
            & $drainRead $state.StderrState

            $line = $null
            while ($state.PendingLines.TryDequeue([ref]$line)) {
                if ($OnOutput) { & $OnOutput $line }
            }

            if (-not ($state.Process.HasExited -and $state.StdoutState.Closed -and $state.StderrState.Closed)) {
                return
            }

            $sender.Stop()
            # Drain any remaining lines after process exit
            while ($state.PendingLines.TryDequeue([ref]$line)) {
                if ($OnOutput) { & $OnOutput $line }
            }
            $state.Process.WaitForExit()
            if ($state.Lines.Count -gt $script:MaxOutputLines) {
                $state.Lines.RemoveRange(0, $state.Lines.Count - $script:MaxOutputLines)
            }
            $result = [NcsRunResult]::new()
            $result.Action = $Request.Playbook
            $result.Command = $remoteCommand
            $result.ExitCode = $state.Process.ExitCode
            $result.Succeeded = $state.Process.ExitCode -eq 0
            $result.StartedAt = $state.StartedAt
            $result.EndedAt = Get-Date
            $result.Duration = $result.EndedAt.Value - $state.StartedAt
            $result.OutputLines = $state.Lines.ToArray()
            $result.DetectedPaths = Find-NcsDetectedPaths -Lines $result.OutputLines

            $state.Process.Dispose()
            $script:NcsActiveExecutionState = $null

            if ($OnCompleted) { & $OnCompleted $result }
        } catch {
            $sender.Stop()
            if ($null -ne $script:NcsActiveExecutionState) {
                $script:NcsActiveExecutionState.Process.Dispose()
                $script:NcsActiveExecutionState = $null
            }
            throw
        }
    }.GetNewClosure()
    $executionState.DrainTimer.Add_Tick($tickHandler)

    try {
        $script:NcsActiveExecutionState = $executionState
        [void] $executionState.Process.Start()
        $executionState.StdoutState.Reader = $executionState.Process.StandardOutput
        $executionState.StderrState.Reader = $executionState.Process.StandardError
        if ($null -ne $askPassSecret) {
            $executionState.Process.StandardInput.WriteLine($askPassSecret)
        } else {
            $executionState.Process.StandardInput.WriteLine("")
        }
        $executionState.Process.StandardInput.Close()
        & $startRead $executionState.StdoutState
        & $startRead $executionState.StderrState
        $executionState.DrainTimer.Start()
    } catch {
        $executionState.DrainTimer.Stop()
        $executionState.Process.Dispose()
        $script:NcsActiveExecutionState = $null
        throw
    }

    return [pscustomobject]@{
        Process       = $executionState.Process
        DrainTimer    = $executionState.DrainTimer
        RemoteCommand = $remoteCommand
        StartedAt     = $executionState.StartedAt
    }
}

function Stop-NcsRemoteCommand {
    param(
        [Parameter(Mandatory)]
        $Handle
    )

    if ($Handle.PSObject.Properties.Match('DrainTimer').Count -gt 0 -and $null -ne $Handle.DrainTimer) {
        $Handle.DrainTimer.Stop()
    }

    if ($null -ne $script:NcsActiveExecutionState -and $Handle.Process -eq $script:NcsActiveExecutionState.Process) {
        $script:NcsActiveExecutionState = $null
    }

    if ($Handle.Process -and -not $Handle.Process.HasExited) {
        $Handle.Process.Kill($true)
    }
}
