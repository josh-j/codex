Set-StrictMode -Version Latest

# NcsConsole.Schedules — Read/write schedule YAML and query remote timers.
# YAML parsing/serialization is delegated to PyYAML on the remote host so the
# console never needs a PowerShell YAML library.

$script:NcsYamlToJsonCmd = "python3 -c 'import yaml,json,sys; print(json.dumps(yaml.safe_load(sys.stdin) or {}))'"
$script:NcsJsonToYamlCmd = "python3 -c 'import yaml,json,sys; sys.stdout.write(yaml.safe_dump(json.load(sys.stdin), sort_keys=False, default_flow_style=False))'"

function ConvertFrom-NcsScheduleData {
    <#
    .SYNOPSIS Convert a parsed schedules payload (JSON → hashtable) into NcsScheduleEntry[].
    #>
    param(
        [AllowNull()]
        [object] $Data
    )

    $schedules = [System.Collections.Generic.List[NcsScheduleEntry]]::new()
    if ($null -eq $Data) { return $schedules.ToArray() }

    $items = $null
    if ($Data -is [hashtable] -and $Data.ContainsKey('schedules')) {
        $items = $Data['schedules']
    }
    if ($null -eq $items) { return $schedules.ToArray() }

    foreach ($item in @($items)) {
        if ($null -eq $item -or $item -isnot [hashtable]) { continue }
        if (-not $item.ContainsKey('name')) { continue }

        $entry = [NcsScheduleEntry]::new()
        $entry.Name = [string]$item['name']
        if ($item.ContainsKey('description'))       { $entry.Description      = [string]$item['description'] }
        if ($item.ContainsKey('playbook'))          { $entry.Playbook         = [string]$item['playbook'] }
        if ($item.ContainsKey('calendar'))          { $entry.Calendar         = [string]$item['calendar'] }
        if ($item.ContainsKey('limit'))             { $entry.Limit            = [string]$item['limit'] }
        if ($item.ContainsKey('tags'))              { $entry.Tags             = [string]$item['tags'] }
        if ($item.ContainsKey('extra_args'))        { $entry.ExtraArgs        = [string]$item['extra_args'] }
        if ($item.ContainsKey('check_mode'))        { $entry.CheckMode        = [bool]$item['check_mode'] }
        if ($item.ContainsKey('enabled'))           { $entry.Enabled          = [bool]$item['enabled'] }
        if ($item.ContainsKey('notify_on_failure')) { $entry.NotifyOnFailure  = [bool]$item['notify_on_failure'] }
        if ($item.ContainsKey('timeout_minutes'))   { $entry.TimeoutMinutes   = [int]$item['timeout_minutes'] }
        $schedules.Add($entry)
    }
    return $schedules.ToArray()
}

function ConvertTo-NcsScheduleJson {
    <#
    .SYNOPSIS Serialize NcsScheduleEntry[] as a compact JSON document shaped like schedules.yml.
    Optional fields are omitted when they match the class default so the dumped YAML stays concise.
    #>
    param(
        [Parameter(Mandatory)]
        [NcsScheduleEntry[]] $Schedules
    )

    $defaults = [NcsScheduleEntry]::new()
    $items = [System.Collections.Generic.List[object]]::new()
    foreach ($s in $Schedules) {
        $item = [ordered]@{ name = $s.Name }
        if ($s.Description) { $item.description = $s.Description }
        $item.playbook = $s.Playbook
        $item.calendar = $s.Calendar
        if ($s.Limit)     { $item.limit = $s.Limit }
        if ($s.Tags)      { $item.tags = $s.Tags }
        if ($s.ExtraArgs) { $item.extra_args = $s.ExtraArgs }
        if ($s.CheckMode) { $item.check_mode = $true }
        $item.enabled = $s.Enabled
        $item.notify_on_failure = $s.NotifyOnFailure
        if ($s.TimeoutMinutes -ne $defaults.TimeoutMinutes) { $item.timeout_minutes = $s.TimeoutMinutes }
        $items.Add([pscustomobject]$item)
    }
    return (@{ schedules = @($items) } | ConvertTo-Json -Depth 5 -Compress)
}

function Save-NcsRemoteSchedules {
    <#
    .SYNOPSIS Write schedules.yml to the remote Ansible host via SSH.
    .OUTPUTS $true on success, $false on failure.
    #>
    param(
        [Parameter(Mandatory)]
        [NcsConsoleSettings] $Settings,
        [Parameter(Mandatory)]
        [NcsScheduleEntry[]] $Schedules
    )

    $json = ConvertTo-NcsScheduleJson -Schedules $Schedules
    $inner = New-NcsRemoteHeredocCommand `
        -Preamble ("$script:NcsJsonToYamlCmd > schedules.yml") `
        -Content $json `
        -Sentinel 'NCSSCHEDULES'
    $cmd = New-NcsRepoShellCommand -Settings $Settings -Command $inner
    $probe = Invoke-NcsSshProbe -Settings $Settings -RemoteCommand $cmd

    return $probe.ExitCode -eq 0
}

$script:NcsTimerStatusQuery = @(
    "echo '---NCSTIMERS---'",
    "systemctl list-timers 'ncs-*' --no-pager --plain 2>/dev/null",
    "echo '---NCSFAILED---'",
    "systemctl list-units 'ncs-*.service' --state=failed --no-pager --plain 2>/dev/null"
) -join '; '

function Get-NcsTimerStatusQueryCommand {
    return $script:NcsTimerStatusQuery
}

function Read-NcsTimerStatusFromOutput {
    <#
    .SYNOPSIS Parse timer/failed status from stdout following an ---NCSTIMERS--- sentinel.
    #>
    param(
        [Parameter(Mandatory)]
        [AllowEmptyString()]
        [string] $StdOut
    )

    $status = @{}
    $afterTimers = $StdOut -split '---NCSTIMERS---', 2
    if ($afterTimers.Count -lt 2) { return $status }
    $sections = $afterTimers[1] -split '---NCSFAILED---', 2
    $timersOut = if ($sections.Count -ge 1) { $sections[0] } else { "" }
    $failedOut = if ($sections.Count -ge 2) { $sections[1] } else { "" }

    # list-timers columns: NEXT, LEFT, LAST, PASSED, UNIT, ACTIVATES
    foreach ($line in ($timersOut -split "`n")) {
        if ($line -match 'ncs-([a-z0-9-]+)\.timer') {
            $name = $Matches[1]
            $columns = $line.Trim() -split '\s{2,}'
            $status[$name] = @{
                Next   = if ($columns.Count -ge 1) { $columns[0] } else { "" }
                Last   = if ($columns.Count -ge 3) { $columns[2] } else { "" }
                Active = $true
            }
        }
    }

    foreach ($line in ($failedOut -split "`n")) {
        if ($line -match 'ncs-([a-z0-9-]+)\.service') {
            $name = $Matches[1]
            if ($status.ContainsKey($name)) {
                $status[$name].LastResult = "failed"
            } else {
                $status[$name] = @{ Next = ""; Last = ""; Active = $false; LastResult = "failed" }
            }
        }
    }

    return $status
}

function Get-NcsRemoteTimerStatus {
    <#
    .SYNOPSIS Query systemd timer status for NCS schedule timers via SSH.
    .OUTPUTS Hashtable mapping schedule name → @{ Next; Last; Active }.
    #>
    param(
        [Parameter(Mandatory)]
        [NcsConsoleSettings] $Settings
    )

    $probe = Invoke-NcsSshProbe -Settings $Settings -RemoteCommand (Get-NcsTimerStatusQueryCommand)
    if ($probe.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($probe.StdOut)) {
        return @{}
    }
    return Read-NcsTimerStatusFromOutput -StdOut $probe.StdOut
}

function Get-NcsRemoteScheduleSnapshot {
    <#
    .SYNOPSIS Fetch schedules.yml (as JSON via remote PyYAML) and timer status in a single SSH call.
    .OUTPUTS @{ Schedules = NcsScheduleEntry[]; TimerStatus = Hashtable }.
    #>
    param(
        [Parameter(Mandatory)]
        [NcsConsoleSettings] $Settings
    )

    $cmd = "{ (cat schedules.yml 2>/dev/null || echo 'schedules: []') | $script:NcsYamlToJsonCmd; } 2>/dev/null || echo '{}'; " + (Get-NcsTimerStatusQueryCommand)
    $probe = Invoke-NcsSshProbe -Settings $Settings -RemoteCommand (New-NcsRepoShellCommand -Settings $Settings -Command $cmd)
    if ($probe.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($probe.StdOut)) {
        return @{ Schedules = @(); TimerStatus = @{} }
    }

    $jsonOut = ($probe.StdOut -split '---NCSTIMERS---', 2)[0]
    $data = $null
    try {
        if (-not [string]::IsNullOrWhiteSpace($jsonOut)) {
            $data = $jsonOut | ConvertFrom-Json -AsHashtable
        }
    } catch {
        Write-Warning "Get-NcsRemoteScheduleSnapshot: failed to parse schedules.yml JSON: $($_.Exception.Message)"
        $data = $null
    }

    return @{
        Schedules   = ConvertFrom-NcsScheduleData -Data $data
        TimerStatus = Read-NcsTimerStatusFromOutput -StdOut $probe.StdOut
    }
}
