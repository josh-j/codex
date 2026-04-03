Set-StrictMode -Version Latest

$script:NcsProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$script:MaxOutputLines = 50000
$script:NcsActiveExecutionState = $null
$script:NcsRemotePidPattern = '^\[\d{2}:\d{2}:\d{2}\]\s+NCS_REMOTE_PID:(\d+)$'
$script:NcsRemoteRunRoot = '.cache/ncs-console'

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

function Get-NcsSshEnvironment {
    param(
        [Parameter(Mandatory)]
        [NcsConsoleSettings] $Settings
    )

    $authMode = $Settings.SshAuthMode
    if ($authMode -eq [NcsSshAuthMode]::Password.ToString() -and -not [string]::IsNullOrWhiteSpace($Settings.SshPassword)) {
        return New-NcsSshAskPassEnvironment -Secret $Settings.SshPassword
    }

    if ($authMode -eq [NcsSshAuthMode]::KeyFile.ToString() -and -not [string]::IsNullOrWhiteSpace($Settings.SshKeyPassphrase)) {
        return New-NcsSshAskPassEnvironment -Secret $Settings.SshKeyPassphrase
    }

    return $null
}

function Add-NcsSshCommonOptions {
    param(
        [Parameter(Mandatory)]
        [System.Collections.Generic.List[string]] $Arguments,
        [Parameter(Mandatory)]
        [NcsConsoleSettings] $Settings
    )

    $Arguments.Add("-o")
    $Arguments.Add("BatchMode=no")
    $Arguments.Add("-o")
    $Arguments.Add("ConnectTimeout=$($Settings.ConnectTimeoutSeconds)")
    $Arguments.Add("-o")
    $Arguments.Add("ServerAliveInterval=$($Settings.ServerAliveIntervalSeconds)")
    $Arguments.Add("-o")
    $Arguments.Add("ServerAliveCountMax=$($Settings.ServerAliveCountMax)")
    $Arguments.Add("-o")
    $Arguments.Add("StrictHostKeyChecking=$($Settings.StrictHostKeyChecking)")
    $Arguments.Add("-o")
    $Arguments.Add("LogLevel=ERROR")
}

function Add-NcsSshAuthOptions {
    param(
        [Parameter(Mandatory)]
        [System.Collections.Generic.List[string]] $Arguments,
        [Parameter(Mandatory)]
        [NcsConsoleSettings] $Settings
    )

    $authMode = [System.Enum]::Parse([NcsSshAuthMode], $Settings.SshAuthMode)
    switch ($authMode) {
        ([NcsSshAuthMode]::Agent) {
            $Arguments.Add("-o")
            $Arguments.Add("PreferredAuthentications=publickey")
        }
        ([NcsSshAuthMode]::KeyFile) {
            if ([string]::IsNullOrWhiteSpace($Settings.SshKeyPath)) {
                throw "KeyFile authentication requires an SSH key path."
            }

            $Arguments.Add("-i")
            $Arguments.Add($Settings.SshKeyPath)
            $Arguments.Add("-o")
            $Arguments.Add("IdentitiesOnly=yes")
        }
        ([NcsSshAuthMode]::Password) {
            $Arguments.Add("-o")
            $Arguments.Add("PreferredAuthentications=password,keyboard-interactive")
            $Arguments.Add("-o")
            $Arguments.Add("PubkeyAuthentication=no")
        }
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
    $arguments.Add("-T")
    Add-NcsSshCommonOptions -Arguments $arguments -Settings $Settings
    Add-NcsSshAuthOptions -Arguments $arguments -Settings $Settings

    $arguments.Add((Get-NcsSshTarget -Settings $Settings))
    $arguments.Add($RemoteCommand)
    return $arguments
}

function Get-NcsSessionLogPath {
    param(
        [Parameter(Mandatory)]
        [NcsConsoleSettings] $Settings,
        [Parameter(Mandatory)]
        [NcsActionRequest] $Request,
        [Parameter(Mandatory)]
        [datetime] $StartedAt
    )

    $dir = $Settings.LogDirectory
    if ([string]::IsNullOrWhiteSpace($dir)) {
        $dir = Join-Path -Path $HOME -ChildPath ".ncs-console-logs"
    }

    if (-not (Test-Path -LiteralPath $dir)) {
        [System.IO.Directory]::CreateDirectory($dir) | Out-Null
    }

    $safeAction = ($Request.Playbook -replace '[^A-Za-z0-9_.-]+', '_').Trim('_')
    if ([string]::IsNullOrWhiteSpace($safeAction)) {
        $safeAction = "run"
    }

    return Join-Path -Path $dir -ChildPath ("{0}_{1}.log" -f $StartedAt.ToString("yyyyMMdd_HHmmss"), $safeAction)
}

function Write-NcsSessionLog {
    param(
        [Parameter(Mandatory)]
        [string] $Path,
        [Parameter(Mandatory)]
        [NcsRunResult] $Result
    )

    $header = @(
        "action=$($Result.Action)"
        "exit_code=$($Result.ExitCode)"
        "succeeded=$($Result.Succeeded)"
        "was_cancelled=$($Result.WasCancelled)"
        "failure_stage=$($Result.FailureStage)"
        "failure_reason=$($Result.FailureReason)"
        "started_at=$($Result.StartedAt.ToString('o'))"
        "ended_at=$(if ($Result.EndedAt) { $Result.EndedAt.Value.ToString('o') } else { '' })"
        "duration=$($Result.Duration)"
        "remote_pid=$($Result.RemotePid)"
        "command=$($Result.Command)"
        ""
    )
    $content = @($header + $Result.OutputLines) -join [Environment]::NewLine
    Set-Content -LiteralPath $Path -Value $content -Encoding UTF8
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
        [NcsActionRequest] $Request,
        [Parameter(Mandatory)]
        [string] $RunId
    )

    $repo = ConvertTo-NcsRemotePathExpression -Value $Settings.RemoteRepoPath
    $actionCommand = Resolve-NcsPlaybookCommand -Settings $Settings -Request $Request
    $actionScript = @(
        "set -e"
        "test -d $repo || { echo 'Remote repo path does not exist.' >&2; exit 21; }"
        "cd $repo"
        "test -d inventory/production || { echo 'Missing inventory/production/ on the remote repo.' >&2; exit 22; }"
        "test -f .vaultpass || { echo 'Missing .vaultpass in the remote repo.' >&2; exit 23; }"
        "if [ -f .venv/bin/activate ]; then . .venv/bin/activate; fi"
        "command -v ansible-playbook >/dev/null 2>&1 || { echo 'ansible-playbook not found in .venv or PATH.' >&2; exit 24; }"
        "export PYTHONUNBUFFERED=1"
        "if command -v stdbuf >/dev/null 2>&1; then"
        "  stdbuf -oL -eL $actionCommand"
        "else"
        "  $actionCommand"
        "fi"
    ) -join "`n"

    $runScript = @"
set -u
RUN_ID=$(ConvertTo-NcsBashLiteral -Value $RunId)
RUN_ROOT="`${HOME}/$($script:NcsRemoteRunRoot)"
PID_FILE="`${RUN_ROOT}/`${RUN_ID}.pid"
ACTION_FILE="`${RUN_ROOT}/`${RUN_ID}.sh"
mkdir -p "`${RUN_ROOT}"
cat > "`${ACTION_FILE}" <<'NCSACTION'
$actionScript
NCSACTION
chmod 700 "`${ACTION_FILE}"
cleanup() {
  rm -f "`${PID_FILE}" "`${ACTION_FILE}"
}
trap cleanup EXIT
trap 'if [ -f "`${PID_FILE}" ]; then kill -TERM "`$(cat "`${PID_FILE}")" >/dev/null 2>&1 || true; fi; exit 130' INT TERM HUP
bash "`${ACTION_FILE}" &
child=`$!
printf '%s\n' "`$child" > "`${PID_FILE}"
echo "NCS_REMOTE_PID:`$child"
wait "`$child"
exit `$?
"@

    $runScript = $runScript -replace "`r", ""
    return "bash -lc " + (ConvertTo-NcsBashLiteral -Value $runScript)
}

function Resolve-NcsFailureStage {
    param(
        [int] $ExitCode,
        [string[]] $Lines
    )

    # Exit codes 21-24 are set by the remote wrapper before ansible runs,
    # so they're reliable even when output hasn't fully flushed.
    switch ($ExitCode) {
        130 { return "cancel" }
        255 { return "ssh" }
        21  { return "remote-setup" }
        22  { return "remote-setup" }
        23  { return "remote-setup" }
        24  { return "remote-setup" }
    }

    # Fallback: infer from tail of output when exit code is ambiguous
    $joined = ($Lines | Select-Object -Last 30) -join "`n"
    if ($joined -match 'Permission denied|Host key verification failed|Authentication failed|Could not resolve hostname|Connection timed out|No route to host') {
        return "ssh"
    }
    if ($joined -match 'Remote repo path does not exist|Missing inventory/production|Missing \.vaultpass|ansible-playbook not found') {
        return "remote-setup"
    }
    return "ansible"
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
        [scriptblock] $OnOutputBatch,
        [scriptblock] $OnCompleted,
        [scriptblock] $OnStale,
        [int] $StaleSeconds = 120
    )

    $runId = [guid]::NewGuid().ToString("N")
    $remoteCommand = Get-NcsRemoteShellCommand -Settings $Settings -Request $Request -RunId $runId

    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = "ssh.exe"
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    foreach ($argument in (Get-NcsSshArgumentList -Settings $Settings -RemoteCommand $remoteCommand)) {
        $psi.ArgumentList.Add($argument)
    }

    $sshEnvironment = Get-NcsSshEnvironment -Settings $Settings
    if ($null -ne $sshEnvironment) {
        foreach ($key in $sshEnvironment.Keys) {
            $psi.Environment[$key] = $sshEnvironment[$key]
        }
    }

    $pendingLines = [System.Collections.Concurrent.ConcurrentQueue[string]]::new()
    $stdoutClosed = [System.Threading.ManualResetEventSlim]::new($false)
    $stderrClosed = [System.Threading.ManualResetEventSlim]::new($false)
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $psi
    $process.EnableRaisingEvents = $true
    $startedAt = Get-Date
    $sessionLogPath = Get-NcsSessionLogPath -Settings $Settings -Request $Request -StartedAt $startedAt

    $stdoutData = [pscustomobject]@{ Queue = $pendingLines; Closed = $stdoutClosed }
    Register-ObjectEvent -InputObject $process -EventName 'OutputDataReceived' -Action {
        $data = $Event.SourceEventArgs.Data
        if ($null -ne $data) {
            $stamped = "[{0}] {1}" -f ([System.DateTime]::Now.ToString("HH:mm:ss")), $data
            $Event.MessageData.Queue.Enqueue($stamped)
        } else {
            $Event.MessageData.Closed.Set()
        }
    } -MessageData $stdoutData -SupportEvent | Out-Null

    $stderrData = [pscustomobject]@{ Queue = $pendingLines; Closed = $stderrClosed }
    Register-ObjectEvent -InputObject $process -EventName 'ErrorDataReceived' -Action {
        $data = $Event.SourceEventArgs.Data
        if ($null -ne $data) {
            $stamped = "[{0}] [stderr] {1}" -f ([System.DateTime]::Now.ToString("HH:mm:ss")), $data
            $Event.MessageData.Queue.Enqueue($stamped)
        } else {
            $Event.MessageData.Closed.Set()
        }
    } -MessageData $stderrData -SupportEvent | Out-Null

    [void] $process.Start()
    $process.BeginOutputReadLine()
    $process.BeginErrorReadLine()

    if ($null -ne $sshEnvironment -and $sshEnvironment.ContainsKey('NCS_UI_PASS')) {
        $process.StandardInput.WriteLine($sshEnvironment['NCS_UI_PASS'])
    } else {
        $process.StandardInput.WriteLine("")
    }
    $process.StandardInput.Close()

    $allLines = [System.Collections.Generic.List[string]]::new()
    $drainTimer = [System.Windows.Threading.DispatcherTimer]::new()
    $drainTimer.Interval = [System.TimeSpan]::FromMilliseconds(100)

    $script:NcsActiveExecutionState = [pscustomobject]@{
        Process        = $process
        DrainTimer     = $drainTimer
        StdoutClosed   = $stdoutClosed
        StderrClosed   = $stderrClosed
        Lines          = $allLines
        PendingLines   = $pendingLines
        StartedAt      = $startedAt
        OnOutput       = $OnOutput
        OnOutputBatch  = $OnOutputBatch
        OnCompleted    = $OnCompleted
        OnStale        = $OnStale
        StaleSeconds   = $StaleSeconds
        Request        = $Request
        RemoteCmd      = $remoteCommand
        RunId          = $runId
        Settings       = $Settings
        SessionLogPath = $sessionLogPath
        DrainCountdown = -1
        LastOutputAt   = $startedAt
        StaleNotified  = $false
        RemotePid      = 0
        State         = "Running"
    }

    $drainTimer.Add_Tick({
        param($sender, $eventArgs)
        try {
            $es = $script:NcsActiveExecutionState
            if ($null -eq $es) {
                $sender.Stop()
                return
            }

            $now = Get-Date
            $line = $null
            $gotOutput = $false
            while ($es.PendingLines.TryDequeue([ref]$line)) {
                if ($line -match $script:NcsRemotePidPattern) {
                    $es.RemotePid = [int] $Matches[1]
                } else {
                    $es.Lines.Add($line)
                    $gotOutput = $true
                    if ($es.OnOutput) { & $es.OnOutput $line }
                }
            }
            if ($gotOutput) {
                $es.LastOutputAt = $now
                $es.StaleNotified = $false
                if ($es.OnOutputBatch) { & $es.OnOutputBatch }
            }

            if (-not $es.Process.HasExited) {
                if (-not $es.StaleNotified -and $es.OnStale) {
                    $idle = ($now - $es.LastOutputAt).TotalSeconds
                    if ($idle -ge $es.StaleSeconds) {
                        $es.StaleNotified = $true
                        & $es.OnStale ([int]$idle)
                    }
                }
                return
            }
            # Process exited — drain a few more ticks to collect final output
            if ($es.DrainCountdown -lt 0) {
                $es.DrainCountdown = 3
                return
            }
            if ($es.DrainCountdown -gt 0) {
                $es.DrainCountdown--
                return
            }

            $sender.Stop()
            $es.Process.WaitForExit()

            if ($es.Lines.Count -gt $script:MaxOutputLines) {
                $es.Lines.RemoveRange(0, $es.Lines.Count - $script:MaxOutputLines)
            }

            $result = [NcsRunResult]::new()
            $result.Action = $es.Request.Playbook
            $result.Command = $es.RemoteCmd
            $result.ExitCode = $es.Process.ExitCode
            $result.Succeeded = $es.Process.ExitCode -eq 0
            $result.StartedAt = $es.StartedAt
            $result.EndedAt = Get-Date
            $result.Duration = $result.EndedAt.Value - $es.StartedAt
            $result.OutputLines = $es.Lines.ToArray()
            $result.DetectedPaths = Find-NcsDetectedPaths -Lines $result.OutputLines
            $result.RemotePid = $es.RemotePid
            $result.SessionLogPath = $es.SessionLogPath
            $result.PreflightCheckedAt = $null
            $result.WasCancelled = $es.State -eq "Cancelling" -or $es.Process.ExitCode -eq 130
            if (-not $result.Succeeded) {
                $result.FailureStage = Resolve-NcsFailureStage -ExitCode $result.ExitCode -Lines $result.OutputLines
                $result.FailureReason = ($result.OutputLines | Select-Object -Last 10) -join " | "
            }
            Write-NcsSessionLog -Path $es.SessionLogPath -Result $result

            $completedCb = $es.OnCompleted
            $es.StdoutClosed.Dispose()
            $es.StderrClosed.Dispose()
            $es.Process.Dispose()
            $script:NcsActiveExecutionState = $null

            if ($completedCb) { & $completedCb $result }
        } catch {
            $sender.Stop()
            if ($null -ne $script:NcsActiveExecutionState) {
                try { $script:NcsActiveExecutionState.Process.Kill() } catch [System.InvalidOperationException] {
                    $null = $_ # Process already exited
                }
                $script:NcsActiveExecutionState.Process.Dispose()
                $script:NcsActiveExecutionState = $null
            }
        }
    })
    $drainTimer.Start()

    return [pscustomobject]@{
        Process       = $process
        DrainTimer    = $drainTimer
        RemoteCommand = $remoteCommand
        StartedAt     = $startedAt
        RunId         = $runId
        Settings      = $Settings
    }
}

function Stop-NcsRemoteCommand {
    param(
        [Parameter(Mandatory)]
        $Handle
    )

    if ($null -ne $script:NcsActiveExecutionState -and $Handle.Process -eq $script:NcsActiveExecutionState.Process) {
        $script:NcsActiveExecutionState.State = "Cancelling"
    }

    # Kill local SSH process first so the UI unblocks immediately
    try {
        if ($Handle.Process -and -not $Handle.Process.HasExited) {
            $Handle.Process.Kill($true)
        }
    } catch [System.InvalidOperationException] {
        $null = $_ # Process already exited
    }

    # Send remote kill asynchronously — the remote wrapper's trap handler
    # will also clean up if SSH drops, but this is a best-effort backstop.
    if ($Handle.PSObject.Properties.Match('RunId').Count -gt 0 -and $Handle.PSObject.Properties.Match('Settings').Count -gt 0) {
        $killScript = (@"
RUN_ROOT="`${HOME}/$($script:NcsRemoteRunRoot)"
PID_FILE="`${RUN_ROOT}/$($Handle.RunId).pid"
if [ -f "`${PID_FILE}" ]; then
  kill -TERM "`$(cat "`${PID_FILE}")" >/dev/null 2>&1 || true
fi
"@) -replace "`r", ""
        $remoteCommand = "bash -lc " + (ConvertTo-NcsBashLiteral -Value $killScript)
        try {
            $null = Invoke-NcsToolCommand -FilePath "ssh.exe" -Arguments (Get-NcsSshArgumentList -Settings $Handle.Settings -RemoteCommand $remoteCommand) -Environment (Get-NcsSshEnvironment -Settings $Handle.Settings) -TimeoutMs 10000
        } catch {
            $null = $_ # Best effort — remote process will also be cleaned up by trap
        }
    }
}
