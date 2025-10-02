<#
.SYNOPSIS
    Update ISE network device CSV using DNAC & schema data, enforce property order, and always
    include PasswordEncrypted:Boolean(true|false) immediately after Authentication: Shared Secret:String(128).

.NOTES
    - Export order is forced by rebuilding each object into an [ordered] hashtable and then to PSCustomObject.
    - We export *only* the rebuilt, ordered objects so the CSV header and rows match the desired order.
    - Secrets are never written to the console.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateScript({Test-Path $_ -PathType Leaf})]
    [string]$LocationSchemaPath,
    
    [Parameter(Mandatory=$true)]
    [ValidateScript({Test-Path $_ -PathType Leaf})]
    [string]$DNACExportPath,
    
    [Parameter(Mandatory=$true)]
    [ValidateScript({Test-Path $_ -PathType Leaf})]
    [string]$ISEExportPath,

    [Parameter(Mandatory=$true)]
    [string]$SiteName,

    [Parameter(Mandatory=$true)]
    [string]$OutputPath,

    [Parameter(Mandatory=$false)]
    [switch]$GetBuildingFromHostname,

    [Parameter(Mandatory=$false)]
    [ValidateSet('ISE', 'DNAC')]
    [string]$PreferDataFrom = 'DNAC',

    [Parameter(Mandatory=$false)]
    [string]$RadiusSharedSecret,

    [Parameter(Mandatory=$false)]
    [string]$TacacsSharedSecret,

    [Parameter(Mandatory=$false)]
    [string]$EncryptionKey,

    [Parameter(Mandatory=$false)]
    [string]$AuthenticationKey
)

#region Helper Functions

function Get-BuildingCode {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Label,

        [Parameter(Mandatory=$false)]
        [string]$InputString,

        [Parameter(Mandatory=$true)]
        [array]$Patterns
    )

    if ([string]::IsNullOrWhiteSpace($InputString)) {
        Write-Verbose "$Label is empty or null"
        return $null
    }

    Write-Verbose "Attempting to extract building code from $Label: $InputString"

    foreach ($pattern in $Patterns) {
        if ($InputString -match $pattern) {
            $buildingCode = $Matches[1].Trim()
            if ($buildingCode -match '^\d+[a-zA-Z]?$') {
                $buildingCode = "B$buildingCode"
            }
            Write-Verbose "Extracted building code from $Label: $buildingCode"
            return $buildingCode
        }
    }

    Write-Warning "Could not extract building code from $Label: $InputString"
    return $null
}

function Get-BuildingCodeFromSite {
    param(
        [Parameter(Mandatory=$false)]
        [string]$SitePath
    )

    $patterns = @(
        '([B]\d+)\s*-',              # "B477 - CS HQ"
        '/([B]\d+)[\s\-]',           # "/B364 -" or "/B364 "
        '/([B]\d+)',                 # "/B364"
        'B(\d+)',                    # "B364" anywhere
        '(?i)-Bldg(\d+[a-zA-Z]?)',   # -Bldg382 or -bldg29B
        '-(\d+[a-zA-Z]?)',           # -382 or -29B
        '/(\d+)'                     # "/364" fallback
    )

    return Get-BuildingCode -Label 'Site path' -InputString $SitePath -Patterns $patterns
}

function Get-BuildingCodeFromHostname {
    param(
        [Parameter(Mandatory=$false)]
        [string]$Hostname
    )

    $patterns = @(
        'B(\d+)',                    # "B364"
        '(?i)-Bldg(\d+[a-zA-Z]?)',   # -Bldg382
        '-(\d+[a-zA-Z]?)'            # -382 or -29B
    )

    return Get-BuildingCode -Label 'Hostname' -InputString $Hostname -Patterns $patterns
}

function Get-LocationPathByBuilding {
    param(
        [Parameter(Mandatory=$true)]
        [string]$BuildingCode,
        
        [Parameter(Mandatory=$true)]
        [array]$LocationSchema
    )
    
    if ([string]::IsNullOrWhiteSpace($BuildingCode)) {
        Write-Warning "Building code is empty or null"
        return $null
    }
    if ($LocationSchema.Count -eq 0) {
        Write-Warning "Location schema is empty"
        return $null
    }
    
    Write-Verbose "Searching for building code: $BuildingCode"
    
    foreach ($location in $LocationSchema) {
        $locationName = $location.'Name:String(100):Required'
        if ([string]::IsNullOrWhiteSpace($locationName)) { continue }

        if ($locationName -like "*$BuildingCode*") {
            Write-Verbose "Found matching location: $locationName"
            return $locationName
        }
        if ($locationName -like "*$($BuildingCode.TrimStart('B'))*") {
            Write-Verbose "Found matching location: $locationName"
            return $locationName
        }
    }
    
    Write-Warning "No matching location found for building code: $BuildingCode"
    return $null
}

function Set-NetworkDeviceGroupValue {
    param(
        [Parameter(Mandatory=$false)]
        [string]$OriginalGroups,

        [Parameter(Mandatory=$true)]
        [string]$TargetPrefix,

        [Parameter(Mandatory=$true)]
        [string]$Replacement
    )

    $groups = if (-not [string]::IsNullOrWhiteSpace($OriginalGroups)) {
        $OriginalGroups -split '\|'
    } else {
        @()
    }

    $updatedGroups = @()
    $entryUpdated = $false

    foreach ($group in $groups) {
        if ($group -like "$TargetPrefix*") {
            if (-not $entryUpdated) {
                $updatedGroups += $Replacement
                $entryUpdated = $true
            }
        } else {
            $updatedGroups += $group
        }
    }

    if (-not $entryUpdated) {
        $updatedGroups += $Replacement
    }

    return ($updatedGroups -join '|')
}

function Update-NetworkDeviceGroups {
    param(
        [Parameter(Mandatory=$true)]
        [string]$OriginalGroups,

        [Parameter(Mandatory=$true)]
        [string]$NewLocationPath
    )

    $groups = if (-not [string]::IsNullOrWhiteSpace($OriginalGroups)) {
        $OriginalGroups -split '\|'
    } else {
        @()
    }

    $normalizedGroups = @()
    foreach ($group in $groups) {
        if ($group -like '*#Cisco Switch') {
            $normalizedGroups += 'Device Type#All Device Types#Switch'
        } else {
            $normalizedGroups += $group
        }
    }

    $normalizedGroupsString = if ($normalizedGroups.Count -gt 0) {
        $normalizedGroups -join '|'
    } else {
        $null
    }

    return Set-NetworkDeviceGroupValue -OriginalGroups $normalizedGroupsString -TargetPrefix 'Location#' -Replacement $NewLocationPath
}

function Update-Reachability {
    param(
        [Parameter(Mandatory=$true)]
        [string]$OriginalGroups,

        [Parameter(Mandatory=$true)]
        [ValidateScript({
            if ([string]::IsNullOrWhiteSpace($_)) {
                throw "IP address cannot be empty"
            }
            if ($_ -notmatch '^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$') {
                throw "Invalid IP address format: $_"
            }
            return $true
        })]
        [string]$IP
    )

    $isReachable = $false
    try {
        # Quick 1-ping test with 2s timeout
        $pingResult = Test-Connection -ComputerName $IP -Count 1 -Quiet -ErrorAction Stop -TimeoutSeconds 2
        $isReachable = $pingResult
    } catch {
        Write-Verbose "Failed to test connectivity to $IP : $_"
        $isReachable = $false
    }

    $replacement = "Reachable#Reachable#$(if($isReachable){'Yes'}else{'No'})"

    return Set-NetworkDeviceGroupValue -OriginalGroups $OriginalGroups -TargetPrefix 'Reachable#' -Replacement $replacement
}

function Update-OperationsOwner {
    param(
        [Parameter(Mandatory=$true)]
        [string]$OriginalGroups,

        [Parameter(Mandatory=$true)]
        [string]$OperationsOwner
    )

    $replacement = "Ops Owner#Ops Owner#$OperationsOwner"

    return Set-NetworkDeviceGroupValue -OriginalGroups $OriginalGroups -TargetPrefix 'Ops Owner#' -Replacement $replacement
}

function Merge-DeviceData {
    param(
        [Parameter(Mandatory=$true)]
        $ISEDevice,
        
        [Parameter(Mandatory=$false)]
        $DNACDevice,
        
        [Parameter(Mandatory=$true)]
        [ValidateSet('ISE', 'DNAC')]
        [string]$PreferDataFrom
    )
    
    if (-not $DNACDevice) { return $ISEDevice }
    
    if ($PreferDataFrom -eq 'DNAC') {
        # Device name
        $dnacDeviceName = $DNACDevice.'Device Name'
        if ($dnacDeviceName -and -not [string]::IsNullOrWhiteSpace($dnacDeviceName)) {
            $ISEDevice.'Name:String(32):Required' = ($dnacDeviceName -split '\.')[0]
        }
        # IP
        $dnacIP = $DNACDevice.'IP Address'
        if ($dnacIP -and -not [string]::IsNullOrWhiteSpace($dnacIP)) {
            $ISEDevice.'IP Address:Subnets(a.b.c.d/m#....):Required' = "$dnacIP/32"
        }
        # Platform/model
        $platform = $DNACDevice.Platform
        if ($platform -and -not [string]::IsNullOrWhiteSpace($platform)) {
            if ($platform -like '*,*') { $platform = $platform.Split(',')[0].Trim() }
            $ISEDevice.'Model Name:String(32)' = $platform
        }
    }
    return $ISEDevice
}

function Set-DefaultAuthenticationSettings {
    param(
        [Parameter(Mandatory=$true)]
        $Device,
        
        [Parameter(Mandatory=$false)]
        [string]$RadiusSecret,
        
        [Parameter(Mandatory=$false)]
        [string]$TacacsSecret,
        
        [Parameter(Mandatory=$false)]
        [string]$EncryptKey,
        
        [Parameter(Mandatory=$false)]
        [string]$AuthKey
    )
    
    # --- set desired values on incoming object (no console output of secrets) ---
    $Device.'Authentication:Protocol:String(6)' = 'RADIUS'

    if ($RadiusSecret) {
        $Device.'Authentication:Shared Secret:String(128)' = $RadiusSecret
    }

    if ($EncryptKey) {
        $Device.'EncryptionKey:String(ascii:16|hexa:32)' = $EncryptKey
    }

    if ($AuthKey) {
        $Device.'AuthenticationKey:String(ascii:20|hexa:40)' = $AuthKey
    }
    
    $Device.'InputFormat:String(32)' = 'hexa'
    
    if ($TacacsSecret) {
        $Device.'TACACS:Shared Secret:String(128)' = $TacacsSecret
    }
    
    $Device.'TACACS:Connect Mode Options:String (OFF|ON_LEGACY|ON_DRAFT_COMPLIANT)' = 'ON_DRAFT_COMPLIANT'
    $Device.'SGA:CoA Coa Source Host:String' = ''

    # Ensure presence of the PasswordEncrypted column/value
    if (-not $Device.PSObject.Properties['PasswordEncrypted:Boolean(true|false)']) {
        $Device | Add-Member -MemberType NoteProperty -Name 'PasswordEncrypted:Boolean(true|false)' -Value $true -Force
    }

    $passwordProperty = 'PasswordEncrypted:Boolean(true|false)'
    $targetProperty   = 'Authentication:Shared Secret:String(128)'
    $fallbackProperty = 'Authentication:Protocol:String(6)'

    # Capture existing property order (excluding PasswordEncrypted so it can be reinserted deterministically)
    $propertyOrder = New-Object System.Collections.Generic.List[string]

    foreach ($property in $Device.PSObject.Properties) {
        if ($property.Name -ne $passwordProperty) {
            [void]$propertyOrder.Add($property.Name)
        }
    }

    $insertIndex = $propertyOrder.IndexOf($targetProperty)

    if ($insertIndex -ge 0) {
        $insertIndex++
    } else {
        $insertIndex = $propertyOrder.IndexOf($fallbackProperty)
        if ($insertIndex -ge 0) {
            $insertIndex++
        }
    }

    if ($insertIndex -ge 0) {
        $propertyOrder.Insert($insertIndex, $passwordProperty)
    } else {
        [void]$propertyOrder.Add($passwordProperty)
    }

    return $Device | Select-Object -Property $propertyOrder
}

function Export-SplitCsv {
    param(
        [Parameter(Mandatory=$true)]
        [array]$InputObjects,

        [Parameter(Mandatory=$true)]
        [string]$Path,

        [Parameter(Mandatory=$false)]
        [int]$MaxItemsPerFile = 500
    )

    $exportedPaths = New-Object System.Collections.Generic.List[string]

    if ($null -eq $InputObjects) {
        $inputCollection = @()
    } elseif ($InputObjects -is [System.Collections.IList]) {
        $inputCollection = $InputObjects
    } else {
        $inputCollection = @($InputObjects)
    }

    $totalCount = $inputCollection.Count

    if ($totalCount -le $MaxItemsPerFile) {
        $inputCollection | Export-Csv -Path $Path -NoTypeInformation -ErrorAction Stop
        $exportedPaths.Add($Path) | Out-Null
        return $exportedPaths
    }

    $directory = [System.IO.Path]::GetDirectoryName($Path)
    $extension = [System.IO.Path]::GetExtension($Path)
    $baseName  = [System.IO.Path]::GetFileNameWithoutExtension($Path)

    $offset = 0
    $partNumber = 1

    while ($offset -lt $totalCount) {
        $chunk = $inputCollection | Select-Object -Skip $offset -First $MaxItemsPerFile

        if ($partNumber -eq 1) {
            $chunkPath = $Path
        } else {
            $partFileName = '{0}_part{1}{2}' -f $baseName, $partNumber, $extension
            $chunkPath = if ([string]::IsNullOrEmpty($directory)) { $partFileName } else { [System.IO.Path]::Combine($directory, $partFileName) }
        }

        $chunk | Export-Csv -Path $chunkPath -NoTypeInformation -ErrorAction Stop
        $exportedPaths.Add($chunkPath) | Out-Null

        $offset += $MaxItemsPerFile
        $partNumber++
    }

    return $exportedPaths
}

#endregion

#region Main Execution

try {
    Write-Host "`n=== Network Device Location Update Process ===" -ForegroundColor Green
    Write-Host "`nParameters:" -ForegroundColor Cyan
    Write-Host "  Location Schema : $LocationSchemaPath" -ForegroundColor Gray
    Write-Host "  DNAC Export     : $DNACExportPath" -ForegroundColor Gray
    Write-Host "  ISE Export      : $ISEExportPath" -ForegroundColor Gray
    Write-Host "  Site Name       : $SiteName" -ForegroundColor Gray
    Write-Host "  Output Path     : $OutputPath" -ForegroundColor Gray
    Write-Host "  Data Preference : $PreferDataFrom" -ForegroundColor Gray
    Write-Host "  Building Source : $(if($GetBuildingFromHostname){'Hostname'}else{'DNAC Site'})" -ForegroundColor Gray
    Write-Host ""

    if (-not $RadiusSharedSecret) {
        Write-Warning "No RADIUS shared secret provided. Device authentication settings may be incomplete."
    }
    
    Write-Host "Reading input files..." -ForegroundColor Yellow
    $locationSchema = Import-Csv -Path $LocationSchemaPath -ErrorAction Stop
    $dnacDevices     = Import-Csv -Path $DNACExportPath -ErrorAction Stop
    $iseDevices      = Import-Csv -Path $ISEExportPath -ErrorAction Stop
    
    Write-Host "  Loaded $($locationSchema.Count) location entries" -ForegroundColor Cyan
    Write-Host "  Loaded $($dnacDevices.Count) DNAC devices" -ForegroundColor Cyan
    Write-Host "  Loaded $($iseDevices.Count) ISE devices" -ForegroundColor Cyan
    Write-Host ""
    
    $defaultLocation = if ($locationSchema.Count -gt 0) {
        $locationSchema[0].'Name:String(100):Required'
    } else {
        "Location#All Locations"
    }
    Write-Host "  Default location: $defaultLocation" -ForegroundColor Gray
    Write-Host ""
    
    # Build DNAC lookups
    Write-Host "Creating DNAC device lookup tables..." -ForegroundColor Yellow
    $dnacLookup   = @{}
    $dnacLookupIP = @{}
    
    foreach ($device in $dnacDevices) {
        $deviceName = $device.'Device Name'
        if ($deviceName -and $deviceName.Trim() -ne '') {
            $hostname = ($deviceName -split '\.')[0]
            $dnacLookup[$hostname] = $device
            Write-Verbose "Added to hostname lookup: $hostname"
        }
        $deviceIP = $device.'IP Address'
        if ($deviceIP -and $deviceIP.Trim() -ne '') {
            $dnacLookupIP[$deviceIP] = $device
            Write-Verbose "Added to IP lookup: $deviceIP"
        }
    }
    
    Write-Host "  Created hostname lookup with $($dnacLookup.Count) entries" -ForegroundColor Cyan
    Write-Host "  Created IP lookup with $($dnacLookupIP.Count) entries" -ForegroundColor Cyan
    Write-Host ""
    
    Write-Host "Processing ISE devices..." -ForegroundColor Yellow
    Write-Host ("=" * 80) -ForegroundColor Gray
    
    $stats = @{
        Total            = $iseDevices.Count
        MatchedAndUpdated= 0
        EmptySite        = 0
        NoMatch          = 0
        UsedDefault      = 0
    }
    
    $results = @()
    # Collect *ordered* devices for export
    $orderedIseDevices = New-Object System.Collections.Generic.List[object]
    
    foreach ($iseDevice in $iseDevices) {
        $iseDeviceName = $iseDevice.'Name:String(32):Required'
        $iseDeviceIP   = ($iseDevice.'IP Address:Subnets(a.b.c.d/m#....):Required' -split '/')[0]
        
        $result = [PSCustomObject]@{
            DeviceName = $iseDeviceName
            IPAddress  = $iseDeviceIP
            Status     = ""
            Details    = ""
            Location   = ""
        }
        
        Write-Host "`nDevice: $iseDeviceName ($iseDeviceIP)" -ForegroundColor White
        
        $correctLocationPath = $defaultLocation
        $dnacDevice   = $null
        $buildingCode = $null
        
        # DNAC match by hostname or IP
        if ($dnacLookup.ContainsKey($iseDeviceName)) {
            $dnacDevice = $dnacLookup[$iseDeviceName]
            Write-Host "  ✓ Matched by hostname in DNAC" -ForegroundColor Gray
        } elseif ($dnacLookupIP.ContainsKey($iseDeviceIP)) {
            $dnacDevice = $dnacLookupIP[$iseDeviceIP]
            Write-Host "  ✓ Matched by IP address in DNAC" -ForegroundColor Gray
        }
        
        # Determine building code
        if ($GetBuildingFromHostname) {
            $buildingCode = Get-BuildingCodeFromHostname -Hostname $iseDeviceName
            Write-Host "  Building code from hostname: $buildingCode" -ForegroundColor Gray
        } elseif ($dnacDevice) {
            $sitePath = if ($dnacDevice.PSObject.Properties['Site']) { $dnacDevice.Site } else { $null }
            if ([string]::IsNullOrWhiteSpace($sitePath)) {
                Write-Host "  ⚠ DNAC site path is empty" -ForegroundColor Yellow
                $stats.EmptySite++
                $result.Details = "Empty DNAC site path"
            } else {
                Write-Host "  DNAC Site: $sitePath" -ForegroundColor Gray
                $buildingCode = Get-BuildingCodeFromSite -SitePath $sitePath
            }
        } else {
            Write-Host "  ⚠ No DNAC match found" -ForegroundColor Yellow
            $stats.NoMatch++
            $result.Details = "No DNAC match"
        }
        
        # Compute location
        if ($buildingCode) {
            Write-Host "  Building code: $buildingCode" -ForegroundColor Gray
            $matchedLocation = Get-LocationPathByBuilding -BuildingCode $buildingCode -LocationSchema $locationSchema
            if ($matchedLocation) {
                $correctLocationPath = $matchedLocation
                Write-Host "  ✓ Location: $correctLocationPath" -ForegroundColor Green
                $result.Status  = "Updated"
                $result.Details = "Matched to $buildingCode"
                $stats.MatchedAndUpdated++
            } else {
                Write-Host "  ⚠ No location match for $buildingCode, using default" -ForegroundColor Yellow
                $result.Status  = "Default"
                $result.Details = "No location match"
                $stats.UsedDefault++
            }
        } else {
            Write-Host "  ⚠ Using default location" -ForegroundColor Yellow
            $result.Status = "Default"
            $stats.UsedDefault++
        }
        
        $result.Location = $correctLocationPath
        
        # Merge data based on preference
        $iseDevice = Merge-DeviceData -ISEDevice $iseDevice -DNACDevice $dnacDevice -PreferDataFrom $PreferDataFrom
        
        # Update Network Device Groups + Ops Owner + Reachability
        $originalGroups = $iseDevice.'Network Device Groups:String(100)(Type#Root Name#Name|...):Required'
        $updatedGroups  = Update-NetworkDeviceGroups -OriginalGroups $originalGroups -NewLocationPath $correctLocationPath
        $updatedGroups  = Update-OperationsOwner -OriginalGroups $updatedGroups -OperationsOwner $SiteName
        
        if ($iseDeviceIP -and -not [string]::IsNullOrWhiteSpace($iseDeviceIP)) {
            try {
                $updatedGroups = Update-Reachability -OriginalGroups $updatedGroups -IP $iseDeviceIP
            } catch {
                Write-Verbose "  Could not update reachability: $_"
            }
        }
        $iseDevice.'Network Device Groups:String(100)(Type#Root Name#Name|...):Required' = $updatedGroups
        
        # Set authentication defaults and enforce property order (always insert PasswordEncrypted where required)
        $iseDevice = Set-DefaultAuthenticationSettings -Device $iseDevice `
            -RadiusSecret $RadiusSharedSecret `
            -TacacsSecret $TacacsSharedSecret `
            -EncryptKey $EncryptionKey `
            -AuthKey $AuthenticationKey

        # Collect ordered object for export
        $orderedIseDevices.Add($iseDevice) | Out-Null

        # Append human-readable result row
        $results += $result
    }
    
    Write-Host "`n" + ("=" * 80) -ForegroundColor Gray
    
    Write-Host "`nExporting results..." -ForegroundColor Yellow

    # Export the *ordered* objects so headers & rows preserve desired column order
    # In PowerShell 7+, consider adding -UseQuotes AsNeeded
    $deviceExportPaths = Export-SplitCsv -InputObjects $orderedIseDevices -Path $OutputPath

    # Export summary (mirrors device chunking logic)
    $summaryPath = [System.IO.Path]::ChangeExtension($OutputPath, ".summary.csv")
    $summaryExportPaths = Export-SplitCsv -InputObjects $results -Path $summaryPath
    
    # Display summary
    Write-Host "`n=== Update Summary ===" -ForegroundColor Green
    Write-Host "  Total devices processed    : $($stats.Total)" -ForegroundColor Cyan
    Write-Host "  Successfully matched       : $($stats.MatchedAndUpdated)" -ForegroundColor Green
    Write-Host "  Empty DNAC site paths      : $($stats.EmptySite)" -ForegroundColor Yellow
    Write-Host "  No DNAC match              : $($stats.NoMatch)" -ForegroundColor Yellow
    Write-Host "  Used default location      : $($stats.UsedDefault)" -ForegroundColor Yellow
    if ($deviceExportPaths.Count -le 1) {
        Write-Host "`n  Output file                : $($deviceExportPaths[0])" -ForegroundColor Cyan
    } else {
        Write-Host "`n  Output files               :" -ForegroundColor Cyan
        foreach ($path in $deviceExportPaths) {
            Write-Host "    - $path" -ForegroundColor Cyan
        }
    }

    if ($summaryExportPaths.Count -le 1) {
        Write-Host "  Summary file               : $($summaryExportPaths[0])" -ForegroundColor Cyan
    } else {
        Write-Host "  Summary files              :" -ForegroundColor Cyan
        foreach ($path in $summaryExportPaths) {
            Write-Host "    - $path" -ForegroundColor Cyan
        }
    }
    Write-Host ""
    
} catch {
    Write-Host "`n❌ Error occurred: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Stack trace:" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor Red
    exit 1
}

Write-Host "✓ Process completed successfully!`n" -ForegroundColor Green

#endregion
