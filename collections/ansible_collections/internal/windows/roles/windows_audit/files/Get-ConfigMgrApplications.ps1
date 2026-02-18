param(
    [string[]]$ExcludedPatterns = @()
)

function Get-ApplicationUpdateStatus {
    [CmdletBinding()]
    param()

    $namespace = 'root\ccm\clientSDK'
    $results = @{
        UpdatesNeeded = @()
        AlreadyCurrent = @()
        NotApplicable = @()
        Errors = @()
    }

    try {
        # Get all applications from ConfigMgr
        Write-Verbose "Querying ConfigMgr applications from namespace: $namespace"
        $allApps = Get-CimInstance -Namespace $namespace -ClassName 'CCM_Application' -ErrorAction Stop

        if (-not $allApps) {
            Write-Warning "No applications found in ConfigMgr"
            return $results
        }

        Write-Verbose "Found $($allApps.Count) total applications"

        # Filter to only applicable applications
        $applicableApps = $allApps | Where-Object { $_.ApplicabilityState -eq 'Applicable' }
        Write-Verbose "$($applicableApps.Count) applications are applicable to this client"

        # Group by application ID to find latest available revision for each
        $latestAvailable = @{}
        $applicableApps | Group-Object Id | ForEach-Object {
            $sorted = $_.Group | Sort-Object { [int]$_.Revision } -Descending
            $latest = $sorted | Select-Object -First 1
            $latestAvailable[$_.Name] = @{
                LatestRevision = [int]$latest.Revision
                LatestVersion = $latest.SoftwareVersion
                Name = $latest.Name
                Publisher = $latest.Publisher
                IsMachineTarget = $latest.IsMachineTarget
                AllowedActions = $latest.AllowedActions
            }
        }

        # Check each installed application to see if it needs updating
        $installedApps = $allApps | Where-Object { $_.InstallState -eq 'Installed' }

        foreach ($app in $installedApps) {
            $appInfo = @{
                Name = $app.Name
                Id = $app.Id
                CurrentVersion = $app.SoftwareVersion
                CurrentRevision = [int]$app.Revision
                Publisher = $app.Publisher
                IsMachineTarget = $app.IsMachineTarget
                SupersessionState = $app.SupersessionState
                EvaluationState = $app.EvaluationState
                PercentComplete = $app.PercentComplete
                AllowedActions = $app.AllowedActions
            }

            # Check if there's a newer version available
            if ($latestAvailable.ContainsKey($app.Id)) {
                $latest = $latestAvailable[$app.Id]
                $appInfo.LatestVersion = $latest.LatestVersion
                $appInfo.LatestRevision = $latest.LatestRevision

                # Determine if update is needed
                $needsUpdate = $false
                $updateReason = ""

                # Check if superseded
                if ($app.SupersessionState -eq 'Superseded') {
                    $needsUpdate = $true
                    $updateReason = "Application is superseded"
                }
                # Check if lower revision
                elseif ([int]$app.Revision -lt $latest.LatestRevision) {
                    $needsUpdate = $true
                    $updateReason = "Newer revision available (Current: $($app.Revision), Latest: $($latest.LatestRevision))"
                }
                # Check evaluation state (3 = Available for install, 4 = Past due - will be installed)
                elseif ($app.EvaluationState -in @(3, 4)) {
                    $needsUpdate = $true
                    $updateReason = "Application evaluation state indicates update available"
                }

                # Check if Install action is allowed (required for updates)
                $canUpdate = $latest.AllowedActions -and ($latest.AllowedActions.Name -contains 'Install')

                if ($needsUpdate -and $canUpdate) {
                    $appInfo.NeedsUpdate = $true
                    $appInfo.UpdateReason = $updateReason
                    $results.UpdatesNeeded += $appInfo
                }
                elseif ($needsUpdate -and -not $canUpdate) {
                    $appInfo.NeedsUpdate = $false
                    $appInfo.UpdateReason = "Update needed but Install action not allowed"
                    $results.NotApplicable += $appInfo
                }
                else {
                    $appInfo.NeedsUpdate = $false
                    $appInfo.UpdateReason = "Application is current"
                    $results.AlreadyCurrent += $appInfo
                }
            }
            else {
                # No newer deployment available for this application
                $appInfo.NeedsUpdate = $false
                $appInfo.UpdateReason = "No newer deployment available"
                $appInfo.LatestVersion = $app.SoftwareVersion
                $appInfo.LatestRevision = [int]$app.Revision
                $results.AlreadyCurrent += $appInfo
            }
        }

        # Also check for available applications that aren't installed
        $notInstalled = $applicableApps | Where-Object {
            $_.InstallState -ne 'Installed' -and
            $_.ApplicabilityState -eq 'Applicable' -and
            $_.AllowedActions -and
            $_.AllowedActions.Name -contains 'Install'
        }

        foreach ($app in $notInstalled) {
            $appInfo = @{
                Name = $app.Name
                Id = $app.Id
                CurrentVersion = "Not Installed"
                CurrentRevision = 0
                LatestVersion = $app.SoftwareVersion
                LatestRevision = [int]$app.Revision
                Publisher = $app.Publisher
                IsMachineTarget = $app.IsMachineTarget
                SupersessionState = $app.SupersessionState
                EvaluationState = $app.EvaluationState
                NeedsUpdate = $true
                UpdateReason = "Application not installed but available"
            }
            $results.UpdatesNeeded += $appInfo
        }

    }
    catch {
        Write-Error "Error querying ConfigMgr applications: $_"
        $results.Errors += $_
    }

    return $results
}

try {
    Write-Host "Retrieving ConfigMgr application status..."

    # Get application update status
    $appStatus = Get-ApplicationUpdateStatus

    # Filter out excluded applications
    $appsToUpdate = @()
    $excludedApps = @()
    $alreadyCurrent = @()

    foreach ($app in $appStatus.UpdatesNeeded) {
        $isExcluded = $false
        foreach ($pattern in $ExcludedPatterns) {
            if ($app.Name -like $pattern) {
                $isExcluded = $true
                $excludedApps += @{
                    Name = $app.Name
                    Reason = "Excluded by pattern: $pattern"
                    Version = $app.LatestVersion
                }
                break
            }
        }
        if (-not $isExcluded) {
            $appsToUpdate += @{
                Name = $app.Name
                Version = $app.LatestVersion
                CurrentVersion = $app.CurrentVersion
                Publisher = $app.Publisher
                UpdateReason = $app.UpdateReason
                IsMachineTarget = $app.IsMachineTarget
            }
        }
    }

    foreach ($app in $appStatus.AlreadyCurrent) {
        $isExcluded = $false
        foreach ($pattern in $ExcludedPatterns) {
            if ($app.Name -like $pattern) {
                $isExcluded = $true
                break
            }
        }
        if (-not $isExcluded) {
            $alreadyCurrent += @{
                Name = $app.Name
                Version = $app.CurrentVersion
            }
        }
    }

    # Build summary
    $summary = @{
        TotalApplications = $appStatus.UpdatesNeeded.Count + $appStatus.AlreadyCurrent.Count + $appStatus.NotApplicable.Count
        NeedingUpdates = $appStatus.UpdatesNeeded.Count
        AlreadyCurrent = $appStatus.AlreadyCurrent.Count
        NotApplicable = $appStatus.NotApplicable.Count
        WillBeUpdated = $appsToUpdate.Count
        Excluded = $excludedApps.Count
    }

    Write-Host "`nApplication Status Summary:"
    Write-Host "  Total Applications: $($summary.TotalApplications)"
    Write-Host "  Needing Updates: $($summary.NeedingUpdates)"
    Write-Host "  Already Current: $($summary.AlreadyCurrent)"
    Write-Host "  Will Be Updated: $($summary.WillBeUpdated)"
    Write-Host "  Excluded: $($summary.Excluded)"

    if ($appsToUpdate.Count -gt 0) {
        Write-Host "`nApplications to be updated:"
        foreach ($app in $appsToUpdate) {
            Write-Host "  - $($app.Name) ($($app.CurrentVersion) -> $($app.Version))"
        }
    }

    if ($excludedApps.Count -gt 0) {
        Write-Host "`nExcluded applications:"
        foreach ($app in $excludedApps) {
            Write-Host "  - $($app.Name)"
        }
    }

    # Output JSON for Ansible
    @{
        AllApps = $summary.TotalApplications
        AppsToUpdate = $appsToUpdate
        ExcludedApps = $excludedApps | ForEach-Object { $_.Name }
        AlreadyCurrent = $alreadyCurrent
        Summary = $summary
    } | ConvertTo-Json -Depth 5
}
catch {
    Write-Error "Error in main script execution: $_"
    @{
        AllApps = 0
        AppsToUpdate = @()
        ExcludedApps = @()
        AlreadyCurrent = @()
        Summary = @{
            Error = $_.Exception.Message
        }
    } | ConvertTo-Json -Depth 5
}
