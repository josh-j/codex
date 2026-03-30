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
        "TitleBarDragRegion",
        "TitleBarTitleText",
        "TitleBarSubtitleText",
        "SettingsToggleButton",
        "SettingsCloseButton",
        "SettingsPanel",
        "SettingsSplitter",
        "OperatePanel",
        "MinimizeWindowButton",
        "MaximizeWindowButton",
        "CloseWindowButton",
        "RunStateText",
        "RunMetaText",
        "ConnectionInfoText",
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
        "PreflightStateBadge",
        "PreflightStateText",
        "PreflightSummaryText",
        "PreflightListBox",
        "ActionTreeView",
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
        "ConsolePane",
        "ConsoleSplitter",
        "ConsoleToggleButton",
        "ConsoleShowButton",
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

    $selectedItem = $Controls.ActionTreeView.SelectedItem
    if ($null -eq $selectedItem -or [string]::IsNullOrWhiteSpace($selectedItem.Tag)) {
        return [NcsUiAction]::RunAll.ToString()
    }
    return [string] $selectedItem.Tag
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
        "Succeeded" { "#6e9fff" }
        "Failed"    { "#f2495c" }
        "Canceled"  { "#ff9830" }
        "Blocked"   { "#f2495c" }
        default     { "#1e2228" }
    }
    $Controls.RunStateBorder.Background = Get-NcsBrush -Color $color
}

function Update-NcsWindowChromeState {
    param(
        [Parameter(Mandatory)]
        [System.Windows.Window] $Window,
        [Parameter(Mandatory)]
        [hashtable] $Controls
    )

    if ($Window.WindowState -eq [System.Windows.WindowState]::Maximized) {
        $Controls.MaximizeWindowButton.Content = "❐"
    }
    else {
        $Controls.MaximizeWindowButton.Content = "□"
    }
}

function Set-NcsPreflightState {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls,
        [Parameter(Mandatory)]
        [string] $State
    )

    $controls.PreflightStateText.Text = $State
    $palette = switch ($State) {
        "Passed" { @{ Background = "#182742"; Foreground = "#6e9fff" } }
        "Failed" { @{ Background = "#381e24"; Foreground = "#f06478" } }
        "Stale"  { @{ Background = "#352a19"; Foreground = "#d6a24a" } }
        default  { @{ Background = "#352a19"; Foreground = "#d6a24a" } }
    }
    $controls.PreflightStateBadge.Background = Get-NcsBrush -Color $palette.Background
    $controls.PreflightStateText.Foreground = Get-NcsBrush -Color $palette.Foreground
}

function Update-NcsConnectionInfo {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls
    )

    $sshHost = $Controls.SshHostTextBox.Text.Trim()
    $sshUser = $Controls.SshUserTextBox.Text.Trim()
    $sshPort = $Controls.SshPortTextBox.Text.Trim()

    if ([string]::IsNullOrWhiteSpace($sshHost) -or [string]::IsNullOrWhiteSpace($sshUser)) {
        $Controls.ConnectionInfoText.Text = "not connected"
        return
    }

    if ([string]::IsNullOrWhiteSpace($sshPort) -or $sshPort -eq "22") {
        $Controls.ConnectionInfoText.Text = "${sshUser}@${sshHost}"
    } else {
        $Controls.ConnectionInfoText.Text = "${sshUser}@${sshHost}:${sshPort}"
    }
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
    $targetTag = $Settings.LastAction
    $found = $false
    foreach ($category in @($Controls.ActionTreeView.Items)) {
        foreach ($leaf in @($category.Items)) {
            if ($leaf.Tag -eq $targetTag) {
                $leaf.IsSelected = $true
                $found = $true
                break
            }
        }
        if ($found) { break }
    }
    if (-not $found) {
        $firstCategory = @($Controls.ActionTreeView.Items)[0]
        if ($null -ne $firstCategory) {
            $firstLeaf = @($firstCategory.Items)[0]
            if ($null -ne $firstLeaf) { $firstLeaf.IsSelected = $true }
        }
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

    Update-NcsConnectionInfo -Controls $Controls
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
    $controls.StatusTextBlock.Text = "Ready."
    Set-NcsRunStateBadge -Controls $controls -State "Idle"
    Set-NcsPreflightState -Controls $controls -State "Not Run"
    $controls.RunMetaText.Text = ""
    Update-NcsWindowChromeState -Window $window -Controls $controls
    Update-NcsConnectionInfo -Controls $controls

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

    $neutralBrush = Get-NcsBrush -Color "#8e939c"

    $invalidatePreflight = {
        $state.PreflightResult = $null
        $controls.PreflightSummaryText.Text = "Settings changed. Run preflight again."
        $controls.PreflightSummaryText.Foreground = $neutralBrush
        Set-NcsPreflightState -Controls $controls -State "Stale"
    }

    & $refreshPreview

    $controls.ActionTreeView.Add_SelectedItemChanged({
        param($sender, $eventArgs)
        $item = $eventArgs.NewValue
        if ($null -ne $item -and -not [string]::IsNullOrWhiteSpace($item.Tag)) {
            $state.Settings.LastAction = [string] $item.Tag
            & $refreshPreview
        }
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

    $controls.MinimizeWindowButton.Add_Click({
        $window.WindowState = [System.Windows.WindowState]::Minimized
    })

    $controls.MaximizeWindowButton.Add_Click({
        if ($window.WindowState -eq [System.Windows.WindowState]::Maximized) {
            $window.WindowState = [System.Windows.WindowState]::Normal
        }
        else {
            $window.WindowState = [System.Windows.WindowState]::Maximized
        }
        Update-NcsWindowChromeState -Window $window -Controls $controls
    })

    $controls.CloseWindowButton.Add_Click({
        $window.Close()
    })

    $controls.TitleBarDragRegion.Add_MouseLeftButtonDown({
        param($sender, $eventArgs)

        if ($eventArgs.ClickCount -eq 2) {
            if ($window.ResizeMode -ne [System.Windows.ResizeMode]::NoResize) {
                if ($window.WindowState -eq [System.Windows.WindowState]::Maximized) {
                    $window.WindowState = [System.Windows.WindowState]::Normal
                }
                else {
                    $window.WindowState = [System.Windows.WindowState]::Maximized
                }
                Update-NcsWindowChromeState -Window $window -Controls $controls
            }
            return
        }

        try {
            $window.DragMove()
        } catch {
        }
    })

    $window.Add_StateChanged({
        Update-NcsWindowChromeState -Window $window -Controls $controls
    })

    $settingsColumn = $controls.OperatePanel.ColumnDefinitions[0]

    $openSettings = {
        $settingsColumn.Width = [System.Windows.GridLength]::new(260)
        $settingsColumn.MinWidth = 200
        $controls.SettingsPanel.Visibility = "Visible"
        $controls.SettingsSplitter.Visibility = "Visible"
    }

    $closeSettings = {
        $controls.SettingsPanel.Visibility = "Collapsed"
        $controls.SettingsSplitter.Visibility = "Collapsed"
        $settingsColumn.Width = [System.Windows.GridLength]::new(0)
        $settingsColumn.MinWidth = 0
    }

    $controls.SettingsToggleButton.Add_Click({
        if ($controls.SettingsPanel.Visibility -eq "Visible") {
            & $closeSettings
        } else {
            & $openSettings
        }
    })

    $controls.SettingsCloseButton.Add_Click({ & $closeSettings })

    $consoleColumn = $controls.OperatePanel.ColumnDefinitions[2]

    $controls.ConsoleToggleButton.Add_Click({
        $controls.ConsolePane.Visibility = "Collapsed"
        $controls.ConsoleSplitter.Visibility = "Collapsed"
        $consoleColumn.Width = [System.Windows.GridLength]::new(0)
        $consoleColumn.MinWidth = 0
        $controls.ConsoleShowButton.Visibility = "Visible"
    })

    $controls.ConsoleShowButton.Add_Click({
        $consoleColumn.Width = [System.Windows.GridLength]::new(400)
        $consoleColumn.MinWidth = 250
        $controls.ConsolePane.Visibility = "Visible"
        $controls.ConsoleSplitter.Visibility = "Visible"
        $controls.ConsoleShowButton.Visibility = "Collapsed"
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
                $controls.PreflightSummaryText.Foreground = Get-NcsBrush -Color "#6e9fff"
                $controls.StatusTextBlock.Text = "Preflight passed."
                Set-NcsPreflightState -Controls $controls -State "Passed"
            } else {
                $controls.PreflightSummaryText.Text = "Preflight failed. Resolve the blocking issues before running."
                $controls.PreflightSummaryText.Foreground = Get-NcsBrush -Color "#f2495c"
                $controls.StatusTextBlock.Text = ($preflight.BlockingIssues -join " | ")
                Set-NcsPreflightState -Controls $controls -State "Failed"
            }
        } catch {
            $controls.PreflightSummaryText.Text = "Preflight errored."
            $controls.StatusTextBlock.Text = $_.Exception.Message
            Set-NcsPreflightState -Controls $controls -State "Failed"
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
            if ($controls.ConsolePane.Visibility -eq "Collapsed") {
                $consoleColumn.Width = [System.Windows.GridLength]::new(400)
                $consoleColumn.MinWidth = 250
                $controls.ConsolePane.Visibility = "Visible"
                $controls.ConsoleSplitter.Visibility = "Visible"
                $controls.ConsoleShowButton.Visibility = "Collapsed"
            }

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
