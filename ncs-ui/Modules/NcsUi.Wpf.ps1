Set-StrictMode -Version Latest

$script:BrushConverter = $null
function Get-NcsBrush {
    param([string] $Color)
    if ($null -eq $script:BrushConverter) {
        $script:BrushConverter = [System.Windows.Media.BrushConverter]::new()
    }
    return $script:BrushConverter.ConvertFromString($Color)
}

function Import-NcsWpfAssemblies {
    Add-Type -AssemblyName PresentationCore
    Add-Type -AssemblyName PresentationFramework
    Add-Type -AssemblyName WindowsBase
}

function Get-NcsXamlControlMap {
    param(
        [Parameter(Mandatory)]
        [System.Windows.Window] $Window
    )

    $map = @{}
    foreach ($name in @(
        "RunStateText",
        "RunMetaText",
        "SshHostTextBox",
        "SshPortTextBox",
        "SshUserTextBox",
        "SshAuthModeComboBox",
        "SshKeyPathTextBox",
        "SshPasswordBox",
        "RemoteRepoPathTextBox",
        "RemoteVaultPathTextBox",
        "DefaultSiteTextBox",
        "DefaultHostTextBox",
        "SaveSettingsButton",
        "PreflightButton",
        "PreflightSummaryText",
        "PreflightListBox",
        "ActionComboBox",
        "SiteTextBox",
        "HostTextBox",
        "ExtraArgsTextBox",
        "RunButton",
        "CancelButton",
        "CommandPreviewTextBox",
        "DetectedPathsListBox",
        "CopyOutputButton",
        "ExportOutputButton",
        "ConsoleTextBox",
        "ConsoleHintText",
        "StatusTextBlock",
        "ExitCodeTextBlock",
        "DurationTextBlock",
        "RunStateBorder",
        "SshKeyPathPanel",
        "SshPasswordPanel"
    )) {
        $map[$name] = $Window.FindName($name)
    }

    return $map
}

function ConvertFrom-NcsActionName {
    param(
        [Parameter(Mandatory)]
        [string] $ActionName
    )

    return [System.Enum]::Parse([NcsUiAction], $ActionName)
}

function Get-NcsSelectedActionName {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls
    )

    $displayName = [string] $Controls.ActionComboBox.SelectedItem
    return ConvertFrom-NcsActionDisplayName -DisplayName $displayName
}

function Update-NcsSshAuthVisibility {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls,
        [Parameter(Mandatory)]
        [string] $AuthMode
    )

    $Controls.SshKeyPathPanel.Visibility = if ($AuthMode -eq [NcsSshAuthMode]::KeyFile.ToString()) { "Visible" } else { "Collapsed" }
    $Controls.SshPasswordPanel.Visibility = if ($AuthMode -eq [NcsSshAuthMode]::Password.ToString()) { "Visible" } else { "Collapsed" }
}

function Set-NcsRunStateBadge {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls,
        [Parameter(Mandatory)]
        [string] $State
    )

    $Controls.RunStateText.Text = $State
    $color = switch ($State) {
        "Succeeded" { "#1B6B3A" }
        "Failed"    { "#8B2D2D" }
        "Canceled"  { "#7D6020" }
        "Blocked"   { "#8B2D2D" }
        default     { "#1C6466" }
    }
    $Controls.RunStateBorder.Background = Get-NcsBrush -Color $color
}

function Sync-NcsSettingsFromControls {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls,
        [Parameter(Mandatory)]
        [NcsUiSettings] $Settings
    )

    $Settings.SshHost = $Controls.SshHostTextBox.Text.Trim()
    $portText = $Controls.SshPortTextBox.Text.Trim()
    $parsedPort = 0
    if ([string]::IsNullOrWhiteSpace($portText) -or -not [int]::TryParse($portText, [ref] $parsedPort)) {
        $parsedPort = 22
    }
    if ($parsedPort -lt 1 -or $parsedPort -gt 65535) {
        $parsedPort = 22
    }
    $Settings.SshPort = $parsedPort
    $Settings.SshUser = $Controls.SshUserTextBox.Text.Trim()
    $Settings.SshAuthMode = [string] $Controls.SshAuthModeComboBox.SelectedItem
    $Settings.SshKeyPath = $Controls.SshKeyPathTextBox.Text.Trim()
    $Settings.SshPassword = $Controls.SshPasswordBox.Password
    $Settings.RemoteRepoPath = $Controls.RemoteRepoPathTextBox.Text.Trim()
    $Settings.RemoteVaultPath = $Controls.RemoteVaultPathTextBox.Text.Trim()
    $Settings.DefaultSite = $Controls.DefaultSiteTextBox.Text.Trim()
    $Settings.DefaultAnsibleHost = $Controls.DefaultHostTextBox.Text.Trim()
    $Settings.LastAction = Get-NcsSelectedActionName -Controls $Controls
}

function Sync-NcsControlsFromSettings {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls,
        [Parameter(Mandatory)]
        [NcsUiSettings] $Settings
    )

    $Controls.SshHostTextBox.Text = $Settings.SshHost
    $Controls.SshPortTextBox.Text = [string] $Settings.SshPort
    $Controls.SshUserTextBox.Text = $Settings.SshUser
    $authModes = Get-NcsSshAuthModeNames
    $Controls.SshAuthModeComboBox.ItemsSource = $authModes
    if ($authModes -contains $Settings.SshAuthMode) {
        $Controls.SshAuthModeComboBox.SelectedItem = $Settings.SshAuthMode
    } else {
        $Controls.SshAuthModeComboBox.SelectedItem = [NcsSshAuthMode]::Agent.ToString()
    }
    $Controls.SshKeyPathTextBox.Text = $Settings.SshKeyPath
    $Controls.SshPasswordBox.Password = $Settings.SshPassword
    $Controls.RemoteRepoPathTextBox.Text = $Settings.RemoteRepoPath
    $Controls.RemoteVaultPathTextBox.Text = $Settings.RemoteVaultPath
    $Controls.DefaultSiteTextBox.Text = $Settings.DefaultSite
    $Controls.DefaultHostTextBox.Text = $Settings.DefaultAnsibleHost
    $Controls.SiteTextBox.Text = $Settings.DefaultSite
    $Controls.HostTextBox.Text = $Settings.DefaultAnsibleHost
    $displayMap = Get-NcsUiActionDisplayMap
    $displayNames = @($displayMap.Values)
    $Controls.ActionComboBox.ItemsSource = $displayNames

    $lastDisplayName = ConvertTo-NcsActionDisplayName -EnumName $Settings.LastAction
    if ($displayNames -contains $lastDisplayName) {
        $Controls.ActionComboBox.SelectedItem = $lastDisplayName
    }
    else {
        $Controls.ActionComboBox.SelectedItem = $displayNames[0]
    }

    Update-NcsSshAuthVisibility -Controls $Controls -AuthMode $Settings.SshAuthMode
}

$script:ConsoleCharCount = 0

function Add-NcsConsoleLine {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls,
        [Parameter(Mandatory)]
        [string] $Line
    )

    $appendText = $Line + [Environment]::NewLine
    $Controls.ConsoleTextBox.AppendText($appendText)
    $script:ConsoleCharCount += $appendText.Length
    if ($script:ConsoleCharCount -gt 2000000) {
        $text = $Controls.ConsoleTextBox.Text
        $Controls.ConsoleTextBox.Text = $text.Substring($text.Length - 1600000)
        $script:ConsoleCharCount = 1600000
    }
    $Controls.ConsoleTextBox.ScrollToEnd()
}

function Set-NcsIdleUiState {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls
    )

    $Controls.RunButton.IsEnabled = $true
    $Controls.CancelButton.IsEnabled = $false
}

function Set-NcsRunningUiState {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls
    )

    $Controls.RunButton.IsEnabled = $false
    $Controls.CancelButton.IsEnabled = $true
}

function Update-NcsCommandPreview {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls,
        [Parameter(Mandatory)]
        [NcsUiSettings] $Settings
    )

    $actionName = Get-NcsSelectedActionName -Controls $Controls

    try {
        $request = [NcsActionRequest]::new((ConvertFrom-NcsActionName -ActionName $actionName))
        $request.Site = $Controls.SiteTextBox.Text.Trim()
        $request.Host = $Controls.HostTextBox.Text.Trim()
        $request.ExtraArgs = $Controls.ExtraArgsTextBox.Text.Trim()
        $preview = Get-NcsRemoteShellCommand -Settings $Settings -Request $request
        $Controls.CommandPreviewTextBox.Text = $preview
    } catch {
        $Controls.CommandPreviewTextBox.Text = $_.Exception.Message
    }

    $isRunSite = $actionName -eq [NcsUiAction]::RunSite.ToString()
    $isRunHost = $actionName -in @([NcsUiAction]::RunHost.ToString(), [NcsUiAction]::InventoryHost.ToString())
    $Controls.SiteTextBox.IsEnabled = $isRunSite
    $Controls.HostTextBox.IsEnabled = $isRunHost

    Update-NcsSshAuthVisibility -Controls $Controls -AuthMode ([string] $Controls.SshAuthModeComboBox.SelectedItem)

    if (-not $isRunSite -and [string]::IsNullOrWhiteSpace($Controls.SiteTextBox.Text)) {
        $Controls.SiteTextBox.Text = $Settings.DefaultSite
    }
    if (-not $isRunHost -and [string]::IsNullOrWhiteSpace($Controls.HostTextBox.Text)) {
        $Controls.HostTextBox.Text = $Settings.DefaultAnsibleHost
    }
}

function Format-NcsDuration {
    param(
        [timespan] $Duration
    )

    return $Duration.ToString("hh\:mm\:ss")
}

function Show-NcsUiApp {
    param(
        [Parameter(Mandatory)]
        [string] $ProjectRoot
    )

    Import-NcsWpfAssemblies

    $xamlPath = Join-Path -Path $ProjectRoot -ChildPath "App/MainWindow.xaml"
    [xml] $xaml = Get-Content -LiteralPath $xamlPath -Raw
    $reader = [System.Xml.XmlNodeReader]::new($xaml)
    $window = [Windows.Markup.XamlReader]::Load($reader)
    $controls = Get-NcsXamlControlMap -Window $window

    $settings = Import-NcsUiSettings
    $state = [pscustomobject]@{
        Settings        = $settings
        PreflightResult = $null
        CurrentHandle   = $null
        LastRunResult   = $null
    }

    Sync-NcsControlsFromSettings -Controls $controls -Settings $settings
    Set-NcsIdleUiState -Controls $controls
    $controls.StatusTextBlock.Text = "Load settings or run preflight."
    Set-NcsRunStateBadge -Controls $controls -State "Idle"
    $controls.RunMetaText.Text = "No command started yet."

    $durationTimer = [System.Windows.Threading.DispatcherTimer]::new()
    $durationTimer.Interval = [timespan]::FromSeconds(1)
    $durationTimer.Add_Tick({
        if ($state.CurrentHandle) {
            $elapsed = (Get-Date) - $state.CurrentHandle.StartedAt
            $controls.DurationTextBlock.Text = Format-NcsDuration -Duration $elapsed
        }
    })

    $refreshPreview = {
        Update-NcsCommandPreview -Controls $controls -Settings $state.Settings
    }

    $neutralBrush = Get-NcsBrush -Color "#202020"

    $invalidatePreflight = {
        $state.PreflightResult = $null
        $controls.PreflightSummaryText.Text = "Settings changed. Run preflight again."
        $controls.PreflightSummaryText.Foreground = $neutralBrush
    }

    & $refreshPreview

    $controls.ActionComboBox.Add_SelectionChanged({
        $state.Settings.LastAction = Get-NcsSelectedActionName -Controls $controls
        & $refreshPreview
    })

    $controls.SiteTextBox.Add_TextChanged({ & $refreshPreview })
    $controls.HostTextBox.Add_TextChanged({ & $refreshPreview })
    $controls.ExtraArgsTextBox.Add_TextChanged({ & $refreshPreview })
    $controls.SshHostTextBox.Add_TextChanged({ & $invalidatePreflight; & $refreshPreview })
    $controls.SshPortTextBox.Add_TextChanged({ & $invalidatePreflight; & $refreshPreview })
    $controls.SshUserTextBox.Add_TextChanged({ & $invalidatePreflight; & $refreshPreview })
    $controls.SshAuthModeComboBox.Add_SelectionChanged({ & $invalidatePreflight; & $refreshPreview })
    $controls.SshKeyPathTextBox.Add_TextChanged({ & $invalidatePreflight; & $refreshPreview })
    $controls.SshPasswordBox.Add_PasswordChanged({ & $invalidatePreflight; & $refreshPreview })
    $controls.RemoteRepoPathTextBox.Add_TextChanged({ & $invalidatePreflight; & $refreshPreview })
    $controls.RemoteVaultPathTextBox.Add_TextChanged({ & $invalidatePreflight; & $refreshPreview })
    $controls.DefaultSiteTextBox.Add_TextChanged({ & $invalidatePreflight; & $refreshPreview })
    $controls.DefaultHostTextBox.Add_TextChanged({ & $invalidatePreflight; & $refreshPreview })

    $controls.SaveSettingsButton.Add_Click({
        try {
            Sync-NcsSettingsFromControls -Controls $controls -Settings $state.Settings
            Save-NcsUiSettings -Settings $state.Settings
            $controls.StatusTextBlock.Text = "Settings saved to $(Get-NcsUiSettingsPath)."
            & $refreshPreview
        } catch {
            $controls.StatusTextBlock.Text = "Failed to save settings: $($_.Exception.Message)"
        }
    })

    $controls.PreflightButton.Add_Click({
        try {
            Sync-NcsSettingsFromControls -Controls $controls -Settings $state.Settings
            $controls.PreflightListBox.ItemsSource = $null
            $controls.PreflightSummaryText.Text = "Running preflight..."
            $controls.StatusTextBlock.Text = "Checking SSH, repo, inventory, vault, and remote commands."
            $preflight = Test-NcsRemotePreflight -Settings $state.Settings
            $state.PreflightResult = $preflight
            $controls.PreflightListBox.ItemsSource = $preflight.Checks
            if ($preflight.IsReady) {
                $controls.PreflightSummaryText.Text = "Preflight passed. The app can run remote actions."
                $controls.PreflightSummaryText.Foreground = Get-NcsBrush -Color "#1B6B3A"
                $controls.StatusTextBlock.Text = "Preflight passed."
            } else {
                $controls.PreflightSummaryText.Text = "Preflight failed. Resolve the blocking issues before running."
                $controls.PreflightSummaryText.Foreground = Get-NcsBrush -Color "#8B2D2D"
                $controls.StatusTextBlock.Text = ($preflight.BlockingIssues -join " | ")
            }
        } catch {
            $controls.PreflightSummaryText.Text = "Preflight errored."
            $controls.StatusTextBlock.Text = $_.Exception.Message
        }
    })

    $controls.RunButton.Add_Click({
        try {
            Sync-NcsSettingsFromControls -Controls $controls -Settings $state.Settings
            if (-not $state.PreflightResult -or -not $state.PreflightResult.IsReady) {
                throw "Run preflight successfully before starting a remote action."
            }

            $controls.ConsoleTextBox.Clear()
            $script:ConsoleCharCount = 0
            $controls.DetectedPathsListBox.ItemsSource = $null
            $controls.ExitCodeTextBlock.Text = "-"
            $controls.DurationTextBlock.Text = "-"
            Set-NcsRunStateBadge -Controls $controls -State "Running"
            $selectedAction = Get-NcsSelectedActionName -Controls $controls
            $controls.RunMetaText.Text = $selectedAction
            $controls.StatusTextBlock.Text = "Starting remote command."
            Set-NcsRunningUiState -Controls $controls

            $request = [NcsActionRequest]::new((ConvertFrom-NcsActionName -ActionName $selectedAction))
            $request.Site = $controls.SiteTextBox.Text.Trim()
            $request.Host = $controls.HostTextBox.Text.Trim()
            $request.ExtraArgs = $controls.ExtraArgsTextBox.Text.Trim()
            $handle = Invoke-NcsAction -Settings $state.Settings -Request $request `
                -OnOutput {
                    param($line)
                    $window.Dispatcher.Invoke([action]{
                        Add-NcsConsoleLine -Controls $controls -Line $line
                    })
                } `
                -OnCompleted {
                    param($runResult)
                    $window.Dispatcher.Invoke([action]{
                        $durationTimer.Stop()
                        $state.LastRunResult = $runResult
                        $state.CurrentHandle = $null
                        Set-NcsIdleUiState -Controls $controls
                        Set-NcsRunStateBadge -Controls $controls -State $(if ($runResult.Succeeded) { "Succeeded" } else { "Failed" })
                        $controls.RunMetaText.Text = $runResult.Command
                        $controls.StatusTextBlock.Text = if ($runResult.Succeeded) { "Run completed successfully." } else { "Run failed." }
                        $controls.ExitCodeTextBlock.Text = [string] $runResult.ExitCode
                        $controls.DurationTextBlock.Text = Format-NcsDuration -Duration $runResult.Duration
                        $controls.DetectedPathsListBox.ItemsSource = $runResult.DetectedPaths
                    })
                }
            $state.CurrentHandle = $handle
            $controls.CommandPreviewTextBox.Text = $handle.RemoteCommand
            $durationTimer.Start()
        } catch {
            Set-NcsIdleUiState -Controls $controls
            Set-NcsRunStateBadge -Controls $controls -State "Blocked"
            $controls.StatusTextBlock.Text = $_.Exception.Message
        }
    })

    $controls.CancelButton.Add_Click({
        if (-not $state.CurrentHandle) {
            return
        }

        try {
            $durationTimer.Stop()
            Stop-NcsRemoteCommand -Handle $state.CurrentHandle
            $state.CurrentHandle = $null
            Set-NcsIdleUiState -Controls $controls
            Set-NcsRunStateBadge -Controls $controls -State "Canceled"
            $controls.StatusTextBlock.Text = "The local SSH process was terminated."
        } catch {
            $controls.StatusTextBlock.Text = "Failed to cancel run: $($_.Exception.Message)"
        }
    })

    $controls.CopyOutputButton.Add_Click({
        try {
            $text = $controls.ConsoleTextBox.Text
            if ([string]::IsNullOrWhiteSpace($text)) {
                $controls.StatusTextBlock.Text = "Nothing to copy."
                return
            }
            [System.Windows.Clipboard]::SetText($text)
            $controls.StatusTextBlock.Text = "Console output copied to clipboard."
        } catch {
            $controls.StatusTextBlock.Text = "Clipboard copy failed: $($_.Exception.Message)"
        }
    })

    $controls.ExportOutputButton.Add_Click({
        $dialog = [Microsoft.Win32.SaveFileDialog]::new()
        $dialog.Filter = "Text files (*.txt)|*.txt|Log files (*.log)|*.log|All files (*.*)|*.*"
        $actionTag = if ($state.LastRunResult) { $state.LastRunResult.Action } else { "output" }
        $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $dialog.FileName = "ncs-ui-$actionTag-$timestamp.txt"
        if ($dialog.ShowDialog()) {
            Set-Content -LiteralPath $dialog.FileName -Value $controls.ConsoleTextBox.Text -Encoding UTF8
            $controls.StatusTextBlock.Text = "Output exported to $($dialog.FileName)."
        }
    })

    $window.Add_Closing({
        $durationTimer.Stop()
        if ($state.CurrentHandle) {
            Stop-NcsRemoteCommand -Handle $state.CurrentHandle
            $state.CurrentHandle = $null
        }
    })

    [void] $window.ShowDialog()
}
