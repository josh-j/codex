#Requires -Version 7.0
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

<#
.SYNOPSIS
    Downloads ncs-console dependencies (WebView2 SDK assemblies).
.DESCRIPTION
    Fetches the Microsoft.Web.WebView2 NuGet package and extracts the
    required DLLs into App/lib/WebView2/. Run this once after cloning,
    or to update the WebView2 SDK version.
#>

$WebView2Version = "1.0.3124.44"
$PackageName = "Microsoft.Web.WebView2"

$ScriptRoot = $PSScriptRoot
$LibRoot = Join-Path -Path $ScriptRoot -ChildPath "App/lib/WebView2"

Write-Host "ncs-console dependency setup" -ForegroundColor Cyan
Write-Host "  WebView2 SDK: $PackageName $WebView2Version"
Write-Host "  Target:       $LibRoot"
Write-Host ""

if (Test-Path -LiteralPath (Join-Path -Path $LibRoot -ChildPath "Microsoft.Web.WebView2.Core.dll")) {
    Write-Host "WebView2 assemblies already present. Delete App/lib/WebView2/ to force re-download." -ForegroundColor Yellow
    exit 0
}

$tempDir = Join-Path -Path ([System.IO.Path]::GetTempPath()) -ChildPath "ncs-console-setup-$([System.Guid]::NewGuid().ToString('N').Substring(0,8))"

try {
    New-Item -Path $tempDir -ItemType Directory -Force | Out-Null

    $nupkgPath = Join-Path -Path $tempDir -ChildPath "$PackageName.$WebView2Version.nupkg"
    $lowerName = $PackageName.ToLower()
    $NuGetUrl = "https://api.nuget.org/v3-flatcontainer/$lowerName/$WebView2Version/$lowerName.$WebView2Version.nupkg"

    Write-Host "Downloading $PackageName $WebView2Version..."
    Invoke-WebRequest -Uri $NuGetUrl -OutFile $nupkgPath -UseBasicParsing

    Write-Host "Extracting assemblies..."
    $zipPath = "$nupkgPath.zip"
    Copy-Item -LiteralPath $nupkgPath -Destination $zipPath
    Expand-Archive -LiteralPath $zipPath -DestinationPath $tempDir -Force

    $pkgDir = $tempDir

    if (Test-Path -LiteralPath $LibRoot) {
        Remove-Item -LiteralPath $LibRoot -Recurse -Force
    }
    New-Item -Path $LibRoot -ItemType Directory -Force | Out-Null

    $coreDll = Get-ChildItem -Path $pkgDir -Recurse -Filter "Microsoft.Web.WebView2.Core.dll" |
        Where-Object { $_.FullName -notmatch 'native' } | Select-Object -First 1 -ExpandProperty FullName
    $wpfDll = Get-ChildItem -Path $pkgDir -Recurse -Filter "Microsoft.Web.WebView2.Wpf.dll" |
        Where-Object { $_.FullName -notmatch 'native' } | Select-Object -First 1 -ExpandProperty FullName

    Copy-Item -LiteralPath $coreDll -Destination $LibRoot
    Copy-Item -LiteralPath $wpfDll -Destination $LibRoot

    foreach ($arch in @("x64", "x86")) {
        $loaderSrc = Get-ChildItem -Path $pkgDir -Recurse -Filter "WebView2Loader.dll" |
            Where-Object { $_.FullName -match "runtimes[\\/]win-$arch[\\/]native" } |
            Select-Object -First 1 -ExpandProperty FullName

        if ($null -eq $loaderSrc) {
            $loaderSrc = Get-ChildItem -Path $pkgDir -Recurse -Filter "WebView2Loader.dll" |
                Where-Object { $_.DirectoryName -match $arch } |
                Select-Object -First 1 -ExpandProperty FullName
        }

        if ($null -ne $loaderSrc) {
            $archDir = Join-Path -Path $LibRoot -ChildPath $arch
            New-Item -Path $archDir -ItemType Directory -Force | Out-Null
            Copy-Item -LiteralPath $loaderSrc -Destination $archDir
            Write-Host "  $arch/WebView2Loader.dll"
        } else {
            Write-Warning "WebView2Loader.dll for $arch not found in package."
        }
    }

    Write-Host ""
    Write-Host "SDK setup complete." -ForegroundColor Green
    Get-ChildItem -Path $LibRoot -Recurse -File | ForEach-Object {
        Write-Host "  $($_.FullName.Substring($LibRoot.Length + 1))"
    }

    # Check for WebView2 Evergreen Runtime (required at runtime, separate from SDK)
    Write-Host ""
    $runtimeFound = $false
    $regPaths = @(
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
        "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
        "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    )
    foreach ($rp in $regPaths) {
        $ver = Get-ItemProperty -Path $rp -Name pv -ErrorAction SilentlyContinue
        if ($ver -and $ver.pv -and $ver.pv -ne "0.0.0.0") {
            Write-Host "WebView2 Runtime: $($ver.pv)" -ForegroundColor Green
            $runtimeFound = $true
            break
        }
    }
    if (-not $runtimeFound) {
        Write-Host "WebView2 Evergreen Runtime not found. Installing..." -ForegroundColor Yellow
        $winget = Get-Command winget -ErrorAction SilentlyContinue
        if ($winget) {
            winget install Microsoft.EdgeWebView2Runtime --scope user --silent --accept-source-agreements --accept-package-agreements
            if ($LASTEXITCODE -eq 0) {
                Write-Host "WebView2 Runtime installed." -ForegroundColor Green
            } else {
                Write-Warning "winget install failed (exit $LASTEXITCODE). Install manually: winget install Microsoft.EdgeWebView2Runtime --scope user"
            }
        } else {
            Write-Warning "winget not available. Install WebView2 Runtime manually:"
            Write-Host "  https://developer.microsoft.com/en-us/microsoft-edge/webview2/"
        }
    }
} finally {
    if (Test-Path -LiteralPath $tempDir) {
        Remove-Item -LiteralPath $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
