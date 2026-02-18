<#
.SYNOPSIS
  Gathers raw ESXi host configuration facts via vCenter Proxy.
  SILENT MODE: Suppresses all PowerCLI banner/warning noise.
#>

[CmdletBinding()]
param (
    [Parameter(Mandatory = $true)][string]$vcenter,
    [Parameter(Mandatory = $true)][string]$vcuser,
    [Parameter(Mandatory = $true)][string]$vcpass,
    [Parameter(Mandatory = $false)][string]$cluster,
    [Parameter(Mandatory = $false)][string]$target_host
)

# --- 1. SILENCE POWERCLI NOISE ---
# This is critical for Ansible 'from_json' to work
$ProgressPreference = 'SilentlyContinue'
Set-PowerCLIConfiguration -InvalidCertificateAction Ignore -ParticipateInCEIP $false -Confirm:$false -Scope Session | Out-Null

# --- 2. SETUP CONNECTION ---
$secpasswd = ConvertTo-SecureString $vcpass -AsPlainText -Force
$vccred = New-Object System.Management.Automation.PSCredential ($vcuser, $secpasswd)

Try {
    Connect-VIServer -Server $vcenter -Credential $vccred -Protocol https -ErrorAction Stop | Out-Null
} Catch {
    # Print clean JSON error and exit
    $err = @{ "success" = $false; "error" = "Failed to connect to vCenter: $($_.Exception.Message)" }
    Write-Host ($err | ConvertTo-Json -Compress)
    Exit 1
}

# --- 3. SELECT TARGET HOSTS ---
$vmhosts = @()

if ($target_host) {
    $vmhosts = Get-VMHost -Name $target_host -ErrorAction SilentlyContinue
}
elseif ($cluster -and $cluster -ne "ALL" -and $cluster -ne "") {
    $vmhosts = Get-Cluster -Name $cluster | Get-VMHost | Sort-Object Name
}
else {
    $vmhosts = Get-VMHost | Sort-Object Name
}

if (-not $vmhosts) {
    $err = @{ "success" = $false; "error" = "Host '$target_host' not found in vCenter" }
    Write-Host ($err | ConvertTo-Json -Compress)
    Disconnect-VIServer * -Confirm:$false
    Exit 1
}

$host_data_list = @()

# --- 4. GATHER DATA ---
ForEach ($vmhost in $vmhosts) {
    $view = $vmhost | Get-View

    $host_facts = [ordered]@{
        "name"              = $vmhost.Name
        "version"           = $vmhost.Version
        "build"             = $vmhost.Build
        "uuid"              = $vmhost.Id
        "advanced_settings" = @{}
        "services"          = @{}
        "network"           = @{ "vswitches" = @() }
        "system"            = @{}
        "lockdown_mode"     = "disabled"
        "lockdown_exceptions" = @()
    }

    # A. Advanced Settings
    Get-AdvancedSetting -Entity $vmhost | ForEach-Object {
        $host_facts.advanced_settings[$_.Name] = $_.Value
    }

    # B. Services
    Get-VMHostService -VMHost $vmhost | ForEach-Object {
        $host_facts.services[$_.Key] = @{
            "running" = $_.Running
            "policy"  = $_.Policy
            "label"   = $_.Label
        }
    }

    # C. Network Security
    # [FIX] Added '-Standard' switch.
    # This prevents the "Obsolete" warning by ignoring Distributed Switches
    # (which don't store security policies on the host object anyway).
    $vmhost | Get-VirtualSwitch -Standard | ForEach-Object {
        $host_facts.network.vswitches += @{
            "name"             = $_.Name
            "forged_transmits" = $_.ExtensionData.Spec.Policy.Security.ForgedTransmits
            "mac_changes"      = $_.ExtensionData.Spec.Policy.Security.MacChanges
            "promiscuous"      = $_.ExtensionData.Spec.Policy.Security.AllowPromiscuous
        }
    }

    # D. Lockdown Mode
    if ($view.Config.AdminDisabled) { $host_facts.lockdown_mode = "enabled" }
    if ($view.ConfigManager.HostAccessManager) {
        $access_mgr = Get-View $view.ConfigManager.HostAccessManager
        $host_facts.lockdown_exceptions = $access_mgr.QueryLockdownExceptions()
    }

    # E. ESXCLI
    try {
        $esxcli = Get-EsxCli -VMHost $vmhost -V2
        $host_facts.system["acceptance_level"] = $esxcli.software.acceptance.get.Invoke()

        $crypto = $esxcli.system.settings.encryption.get.Invoke()
        $host_facts.system["crypto_mode"] = $crypto.Mode
        $host_facts.system["secure_boot_required"] = $crypto.RequireSecureBoot
    }
    catch {
        $host_facts.system["esxcli_error"] = $_.Exception.Message
    }

    $host_data_list += $host_facts
}

# --- 5. CLEANUP & OUTPUT ---
Disconnect-VIServer * -Force -Confirm:$false | Out-Null

# Flush buffer to ensure no previous noise remains
[Console]::Out.Flush()

# Generate JSON
$output = [ordered]@{ "success" = $true; "hosts" = $host_data_list; "count" = $host_data_list.Count }
$json_output = $output | ConvertTo-Json -Depth 5

# FINAL OUTPUT - Write strictly to stdout
Write-Host $json_output
