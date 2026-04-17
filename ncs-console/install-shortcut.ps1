#Requires -Version 7.0
<#
.SYNOPSIS
    Create a Windows Desktop shortcut to launch ncs-console.

.DESCRIPTION
    Generates an NCS-branded .ico (a bold white "N" on a dark background
    with an accent band) at App/ncs-icon.ico and creates an "NCS Console"
    shortcut on the current user's Desktop. The shortcut invokes pwsh.exe
    (falling back to Windows PowerShell 5.1 if pwsh is not installed)
    against ncs-console.ps1 with a hidden console window.

.PARAMETER Destination
    Where to write the .lnk. Defaults to the user's Desktop.

.PARAMETER IconPath
    Where to write the generated .ico. Defaults to App/ncs-icon.ico
    alongside the UI assets.

.PARAMETER Force
    Overwrite the shortcut and icon if they already exist.

.PARAMETER Uninstall
    Remove the shortcut (and optionally the icon with -Force).

.EXAMPLE
    pwsh -File .\install-shortcut.ps1
.EXAMPLE
    pwsh -File .\install-shortcut.ps1 -Force
.EXAMPLE
    pwsh -File .\install-shortcut.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [string] $Destination,
    [string] $IconPath,
    [switch] $Force,
    [switch] $Uninstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $IsWindows) {
    throw "install-shortcut.ps1 runs only on Windows."
}

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$entryScript = Join-Path $projectRoot "ncs-console.ps1"

if (-not $Destination) {
    $Destination = Join-Path ([Environment]::GetFolderPath("Desktop")) "NCS Console.lnk"
}
if (-not $IconPath) {
    $IconPath = Join-Path $projectRoot "App\ncs-icon.ico"
}

function New-NcsIcon {
    param([Parameter(Mandatory)][string] $Path)

    Add-Type -AssemblyName System.Drawing

    $size = 256
    $bmp = [System.Drawing.Bitmap]::new($size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    try {
        $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
        $g.Clear([System.Drawing.Color]::FromArgb(255, 0x16, 0x1a, 0x20))

        $accent = [System.Drawing.Color]::FromArgb(255, 0x4f, 0xc3, 0xf7)
        $band = [System.Drawing.SolidBrush]::new($accent)
        try {
            $bandHeight = [int]($size * 0.10)
            $g.FillRectangle($band, 0, $size - $bandHeight, $size, $bandHeight)
        } finally { $band.Dispose() }

        $font = [System.Drawing.Font]::new("Segoe UI", 200, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
        try {
            $format = [System.Drawing.StringFormat]::new()
            $format.Alignment = [System.Drawing.StringAlignment]::Center
            $format.LineAlignment = [System.Drawing.StringAlignment]::Center
            $rect = [System.Drawing.RectangleF]::new(0, -10, $size, $size)
            $g.DrawString("N", $font, [System.Drawing.Brushes]::White, $rect, $format)
        } finally { $font.Dispose() }
    } finally { $g.Dispose() }

    $pngStream = [System.IO.MemoryStream]::new()
    try {
        $bmp.Save($pngStream, [System.Drawing.Imaging.ImageFormat]::Png)
        $pngBytes = $pngStream.ToArray()
    } finally {
        $pngStream.Dispose()
        $bmp.Dispose()
    }

    $dir = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }

    # ICO container wrapping a single 256x256 PNG frame. Windows Vista+
    # accepts PNG-compressed entries in ICO; the classic BMP format is
    # unnecessary at this resolution.
    $fs = [System.IO.File]::Create($Path)
    $bw = [System.IO.BinaryWriter]::new($fs)
    try {
        $bw.Write([uint16]0)                     # reserved
        $bw.Write([uint16]1)                     # type = icon
        $bw.Write([uint16]1)                     # image count
        $bw.Write([byte]0)                       # width  (0 means 256)
        $bw.Write([byte]0)                       # height (0 means 256)
        $bw.Write([byte]0)                       # palette count
        $bw.Write([byte]0)                       # reserved
        $bw.Write([uint16]1)                     # color planes
        $bw.Write([uint16]32)                    # bits per pixel
        $bw.Write([uint32]$pngBytes.Length)      # image size
        $bw.Write([uint32]22)                    # data offset (6-byte header + 16-byte entry)
        $bw.Write($pngBytes)
    } finally {
        $bw.Close()
        $fs.Close()
    }
}

function Remove-NcsShortcut {
    param(
        [string] $Destination,
        [string] $IconPath,
        [switch] $RemoveIcon
    )
    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Force
        Write-Host "✓ Removed shortcut: $Destination"
    } else {
        Write-Host "  No shortcut at $Destination."
    }
    if ($RemoveIcon -and (Test-Path -LiteralPath $IconPath)) {
        Remove-Item -LiteralPath $IconPath -Force
        Write-Host "✓ Removed icon: $IconPath"
    }
}

if ($Uninstall) {
    Remove-NcsShortcut -Destination $Destination -IconPath $IconPath -RemoveIcon:$Force
    return
}

if (-not (Test-Path -LiteralPath $entryScript)) {
    throw "ncs-console.ps1 not found at $entryScript"
}

if ($Force -or -not (Test-Path -LiteralPath $IconPath)) {
    New-NcsIcon -Path $IconPath
    Write-Host "✓ Generated icon: $IconPath"
}

if ((Test-Path -LiteralPath $Destination) -and -not $Force) {
    throw "Shortcut already exists at $Destination. Use -Force to overwrite."
}

$pwshCmd = Get-Command pwsh.exe -ErrorAction SilentlyContinue
if ($pwshCmd) {
    $targetPath = $pwshCmd.Source
} else {
    Write-Warning "pwsh.exe not found; falling back to Windows PowerShell 5.1. Install PowerShell 7+ for best compatibility."
    $targetPath = (Get-Command powershell.exe -ErrorAction Stop).Source
}

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($Destination)
$lnk.TargetPath       = $targetPath
$lnk.Arguments        = "-NoLogo -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$entryScript`""
$lnk.WorkingDirectory = $projectRoot
$lnk.IconLocation     = "$IconPath,0"
$lnk.WindowStyle      = 7    # minimized (WPF window pops above anyway)
$lnk.Description      = "NCS Console — fleet ops UI"
$lnk.Save()

Write-Host "✓ Shortcut created: $Destination"
Write-Host "  Double-click to launch ncs-console. Re-run with -Force to refresh after updates."
