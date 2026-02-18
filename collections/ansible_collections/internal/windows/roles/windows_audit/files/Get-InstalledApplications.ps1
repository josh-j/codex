$registryPaths = @(
    'HKLM:\Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*'
)

$apps = foreach ($path in $registryPaths) {
    Get-ItemProperty $path -ErrorAction SilentlyContinue |
        Where-Object DisplayName -NE $null |
        Select-Object DisplayName, DisplayVersion, Publisher, InstallDate
}

$apps | Sort-Object DisplayName -Unique | ConvertTo-Json -Depth 3
