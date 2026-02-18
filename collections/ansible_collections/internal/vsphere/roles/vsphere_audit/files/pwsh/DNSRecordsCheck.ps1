# Crafted by Rob McLean
# This script uses the Winodws Resolve-DnsName to query
# Forward and reverse DNS records

# First lets clear any old reports from memory
$report = @()
# Now lets load the list of systems to query
$Servers = @(Get-Content -path "C:\Temp\Servers.txt")

#Now lets define our Reports folder
$ReportPath = "C:\Temp\DNS Query Reports"
# Now lets grab the date so we can use it in the report name
$Today = (Get-Date).ToString("g")
    $ReportDate = $Today -replace ' ','_'
    $ReportDate = $ReportDate -replace '[\\/]','_'
    $ReportDate = $ReportDate -replace ':','-'
    $logFile = $ReportPath + "\" + "DNS_Records_Check_" + $ReportDate + ".csv"

# Now lets query some records
ForEach($Server in $Servers){
    Write-Host $Server

    # Process Forward Records
    $System = Resolve-DnsName $Server | Select-Object -Property Name, IPAddress
    $ForwardRecord = $System.Name -replace("@{Name=","") -replace("}","")
    if ($null -eq $ForwardRecord){
        $FRecord = "No Record"
    } # End If
    else {
    $FRecord = "Forward Record found"
    } # End Else

    # Process Reverse Records
    $IPTrimmed = $System.IPAddress -replace("@{IPAddress=","") -replace("}","")
    $ReverseRecord = Resolve-DnsName $IPTrimmed -Type PTR | Select-Object Name
        if ($null -eq $ReverseRecord){
            $TrimmedRR = "No Record"
        } # End If
        else {
            $TrimmedRR = $ReverseRecord.Name -replace("@{Name=","") -replace("}","")
        } # End Else

    # Now lets add teh values to our array
    $dnsObject = New-Object PSObject
    Add-Member -InputObject $dnsObject -MemberType NoteProperty -Name System -Value $Server
    Add-Member -InputObject $dnsObject -MemberType NoteProperty -Name IPAddress -Value $IPTrimmed
    Add-Member -InputObject $dnsObject -MemberType NoteProperty -Name ForwardRecord -Value $FRecord
    Add-Member -InputObject $dnsObject -MemberType NoteProperty -Name ReverseRecord -Value $TrimmedRR

    $report += $dnsObject

    } # End ForEach Loop

    $report | Out-GridView
    $report | Export-Csv -Path $logFile -NoTypeInformation
    Write-Host "Output saved to $logFile"
