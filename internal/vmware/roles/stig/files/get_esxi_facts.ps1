<#
.SYNOPSIS
  Gathers raw ESXi host configuration facts via vCenter Proxy.
  SILENT MODE: Suppresses all PowerCLI banner/warning noise.

  NOTE:
  PowerCLI cmdlets like Get-VMHost may return a single object (not an array).
  This script normalizes those outputs via @() to avoid ".Count" property errors.
#>

[CmdletBinding()]
param (
    [Parameter(Mandatory = $true)][string]$vcenter,
    [Parameter(Mandatory = $true)][string]$vcuser,

    # Allow env-based secret injection (preferred for Ansible).
    [Parameter(Mandatory = $false)][string]$vcpass,

    [Parameter(Mandatory = $false)][string]$cluster,
    [Parameter(Mandatory = $false)][string]$target_host
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-JsonError {
    param([string]$Message)

    $err = [ordered]@{
        success = $false
        error   = $Message
        hosts   = @()
        count   = 0
    }
    Write-Output ($err | ConvertTo-Json -Compress -Depth 8)
}

# --- 1. SILENCE POWERCLI NOISE ---
$ProgressPreference = 'SilentlyContinue'
try {
    Import-Module VMware.PowerCLI -ErrorAction Stop | Out-Null
} catch {
    Write-JsonError ("PowerCLI module not available: " + $_.Exception.Message)
    exit 1
}

try {
    Set-PowerCLIConfiguration -InvalidCertificateAction Ignore -ParticipateInCEIP:$false -Confirm:$false -Scope Session | Out-Null
} catch {
    # Non-fatal; continue
}

# --- 2. RESOLVE PASSWORD (ARG OR ENV) ---
if ([string]::IsNullOrWhiteSpace($vcpass)) {
    $vcpass = $env:VC_PASS
}
if ([string]::IsNullOrWhiteSpace($vcpass)) {
    Write-JsonError "No vCenter password provided. Pass -vcpass or set environment variable VC_PASS."
    exit 1
}

# --- 3. CONNECT ---
$vi = $null
try {
    $secpasswd = ConvertTo-SecureString $vcpass -AsPlainText -Force
    $vccred = New-Object System.Management.Automation.PSCredential ($vcuser, $secpasswd)

    $vi = Connect-VIServer -Server $vcenter -Credential $vccred -Protocol https -ErrorAction Stop -WarningAction SilentlyContinue
} catch {
    Write-JsonError ("Failed to connect to vCenter: " + $_.Exception.Message)
    exit 1
}

# --- 4. SELECT TARGET HOSTS ---
$vmhosts = $null
try {
    if (-not [string]::IsNullOrWhiteSpace($target_host)) {
        $vmhosts = Get-VMHost -Name $target_host -ErrorAction Stop
    }
    elseif (-not [string]::IsNullOrWhiteSpace($cluster) -and $cluster -ne "ALL") {
        $vmhosts = Get-Cluster -Name $cluster -ErrorAction Stop | Get-VMHost -ErrorAction Stop | Sort-Object Name
    }
    else {
        $vmhosts = Get-VMHost -ErrorAction Stop | Sort-Object Name
    }
} catch {
    Write-JsonError ("Failed to resolve target host(s): " + $_.Exception.Message)
    try { Disconnect-VIServer -Server $vi -Force -Confirm:$false | Out-Null } catch {}
    exit 1
}

# Normalize to array to avoid ".Count" errors when a single object is returned
$vmhosts = @($vmhosts)

if ($vmhosts.Count -eq 0) {
    $msg = if ($target_host) { "Host '$target_host' not found in vCenter" } else { "No hosts returned from inventory query" }
    Write-JsonError $msg
    try { Disconnect-VIServer -Server $vi -Force -Confirm:$false | Out-Null } catch {}
    exit 1
}

# --- 5. GATHER DATA ---
$host_data_list = @()

foreach ($vmhost in $vmhosts) {
    $host_facts = [ordered]@{
        name                = $vmhost.Name
        version             = $vmhost.Version
        build               = $vmhost.Build
        uuid                = $vmhost.Id
        advanced_settings   = @{}
        services            = @{}
        network             = @{ vswitches = @() }
        system              = @{}
        lockdown_mode       = "disabled"
        lockdown_exceptions = @()
        errors              = @()
    }

    $view = $null
    try {
        $view = $vmhost | Get-View -ErrorAction Stop
    } catch {
        $host_facts.errors += ("Get-View failed: " + $_.Exception.Message)
        $host_data_list += $host_facts
        continue
    }

    # A. Advanced Settings
    try {
        Get-AdvancedSetting -Entity $vmhost -ErrorAction Stop | ForEach-Object {
            $host_facts.advanced_settings[$_.Name] = $_.Value
        }
    } catch {
        $host_facts.errors += ("Advanced settings failed: " + $_.Exception.Message)
    }

    # B. Services
    try {
        Get-VMHostService -VMHost $vmhost -ErrorAction Stop | ForEach-Object {
            $host_facts.services[$_.Key] = @{
                running = $_.Running
                policy  = $_.Policy
                label   = $_.Label
            }
        }
    } catch {
        $host_facts.errors += ("Service facts failed: " + $_.Exception.Message)
    }

    # C. Network Security (standard vSwitch only)
    try {
        $vmhost | Get-VirtualSwitch -Standard -ErrorAction Stop | ForEach-Object {
            $host_facts.network.vswitches += @{
                name             = $_.Name
                forged_transmits = $_.ExtensionData.Spec.Policy.Security.ForgedTransmits
                mac_changes      = $_.ExtensionData.Spec.Policy.Security.MacChanges
                promiscuous      = $_.ExtensionData.Spec.Policy.Security.AllowPromiscuous
            }
        }
    } catch {
        $host_facts.errors += ("vSwitch facts failed: " + $_.Exception.Message)
    }

    # D. Lockdown Mode
    try {
        if ($view.Config.AdminDisabled) { $host_facts.lockdown_mode = "enabled" }
        if ($view.ConfigManager.HostAccessManager) {
            $access_mgr = Get-View $view.ConfigManager.HostAccessManager -ErrorAction Stop
            $host_facts.lockdown_exceptions = @($access_mgr.QueryLockdownExceptions())
        }
    } catch {
        $host_facts.errors += ("Lockdown facts failed: " + $_.Exception.Message)
    }

    # E. ESXCLI
    try {
        $esxcli = Get-EsxCli -VMHost $vmhost -V2 -ErrorAction Stop
        $host_facts.system["acceptance_level"] = $esxcli.software.acceptance.get.Invoke()

        $crypto = $esxcli.system.settings.encryption.get.Invoke()
        $host_facts.system["crypto_mode"] = $crypto.Mode
        $host_facts.system["secure_boot_required"] = $crypto.RequireSecureBoot
    } catch {
        $host_facts.system["esxcli_error"] = $_.Exception.Message
    }

    $host_data_list += $host_facts
}

# Normalize to array for stable count/type
$host_data_list = @($host_data_list)

# --- 6. CLEANUP ---
try { Disconnect-VIServer -Server $vi -Force -Confirm:$false | Out-Null } catch {}

# --- 7. OUTPUT (STRICT JSON) ---
$output = [ordered]@{
    success = $true
    hosts   = $host_data_list
    count   = $host_data_list.Count
}
Write-Output ($output | ConvertTo-Json -Compress -Depth 10)
