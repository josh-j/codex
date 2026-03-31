Set-StrictMode -Version Latest

$script:NcsProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
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
    $vault = ConvertTo-NcsRemotePathExpression -Value $Settings.RemoteVaultPath
    $command = "ansible-playbook -i $inventory playbooks/$($Request.Playbook) --vault-password-file $vault"

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

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $psi
    $lines = [System.Collections.Generic.List[string]]::new()
    $startedAt = Get-Date

    $outputHandler = [System.Diagnostics.DataReceivedEventHandler]{
        param($s, $e)
        if ($null -eq $e.Data) {
            return
        }

        $timestamped = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $e.Data
        $lines.Add($timestamped)
        if ($OnOutput) {
            & $OnOutput $timestamped
        }
    }

    $completedHandler = [System.EventHandler]{
        param($s, $e)
        $process.WaitForExit()
        if ($lines.Count -gt $script:MaxOutputLines) {
            $lines.RemoveRange(0, $lines.Count - $script:MaxOutputLines)
        }
        $result = [NcsRunResult]::new()
        $result.Action = $Request.Playbook
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
        if ($null -ne $askPassSecret) {
            $process.StandardInput.WriteLine($askPassSecret)
        }
        $process.StandardInput.Close()
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


