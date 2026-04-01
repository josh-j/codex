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

function Invoke-NcsReportMirror {
    param(
        [Parameter(Mandatory)]
        [NcsConsoleSettings] $Settings,
        [Parameter(Mandatory)]
        [string] $LocalRoot
    )

    $cacheParent = Split-Path -Parent $LocalRoot
    if (-not (Test-Path -LiteralPath $cacheParent)) {
        [System.IO.Directory]::CreateDirectory($cacheParent) | Out-Null
    }
    if (Test-Path -LiteralPath $LocalRoot) {
        Remove-Item -LiteralPath $LocalRoot -Recurse -Force
    }
    [System.IO.Directory]::CreateDirectory($LocalRoot) | Out-Null

    $arguments = [System.Collections.Generic.List[string]]::new()
    $arguments.Add("-r")
    $arguments.Add("-P")
    $arguments.Add([string] $Settings.SshPort)
    $arguments.Add("-o")
    $arguments.Add("BatchMode=no")

    $authMode = [System.Enum]::Parse([NcsSshAuthMode], $Settings.SshAuthMode)
    switch ($authMode) {
        ([NcsSshAuthMode]::Agent) {
            $arguments.Add("-o")
            $arguments.Add("PreferredAuthentications=publickey")
        }
        ([NcsSshAuthMode]::KeyFile) {
            if ([string]::IsNullOrWhiteSpace($Settings.SshKeyPath)) {
                throw "KeyFile authentication requires an SSH key path."
            }
            $arguments.Add("-i")
            $arguments.Add($Settings.SshKeyPath)
            $arguments.Add("-o")
            $arguments.Add("IdentitiesOnly=yes")
        }
        ([NcsSshAuthMode]::Password) {
            $arguments.Add("-o")
            $arguments.Add("PreferredAuthentications=password,keyboard-interactive")
            $arguments.Add("-o")
            $arguments.Add("PubkeyAuthentication=no")
        }
    }

    $environment = $null
    if ($authMode -eq [NcsSshAuthMode]::Password -and -not [string]::IsNullOrWhiteSpace($Settings.SshPassword)) {
        $environment = New-NcsSshAskPassEnvironment -Secret $Settings.SshPassword
    } elseif ($authMode -eq [NcsSshAuthMode]::KeyFile -and -not [string]::IsNullOrWhiteSpace($Settings.SshKeyPassphrase)) {
        $environment = New-NcsSshAskPassEnvironment -Secret $Settings.SshKeyPassphrase
    }

    $remoteSpec = "{0}:{1}" -f (Get-NcsSshTarget -Settings $Settings), "/srv/samba/reports"
    $arguments.Add($remoteSpec)
    $arguments.Add($cacheParent)

    return Invoke-NcsToolCommand -FilePath "scp.exe" -Arguments $arguments -Environment $environment -TimeoutMs 180000
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
        "SettingsToggleButton",
        "SettingsCloseButton",
        "SettingsPanel",
        "SettingsSplitter",
        "OperatePanel",
        "OperateToggleButton",
        "OperateContent",
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
        "SaveSettingsButton",
        "PreflightButton",
        "PreflightButtonText",
        "RefreshPlaybooksButton",
        "PlaybookPlaceholder",
        "PlaybookSplitPane",
        "ActionTreeView",
        "ActionPropertiesPanel",
        "ActionSelectionTitle",
        "ActionLimitTextBox",
        "ActionLimitTree",
        "ActionLimitTreeBorder",
        "ActionLimitTreeScroll",
        "ActionTagsTextBox",
        "ActionCheckModeCheckBox",
        "ActionDiffCheckBox",
        "ActionVerbosityComboBox",
        "ActionOptionsPanel",
        "ActionScrollViewer",
        "ExtraArgsTextBox",
        "MutatingWarning",
        "RunButton",
        "CancelButton",
        "CommandPreviewTextBox",
        "DetectedPathsPanel",
        "DetectedPathsListBox",
        "CopyOutputButton",
        "ExportOutputButton",
        "ConsoleTextBox",
        "ConsolePane",
        "ConsoleSplitter",
        "ConsoleToggleButton",
        "ConsoleShowButton",
        "ReportsToggleButton",
        "ReportsPane",
        "ReportsSplitter",
        "ReportPlaceholder",
        "ReportBackButton",
        "ReportHomeButton",
        "ReportRefreshButton",
        "ReportsCloseButton",
        "StatusTextBlock",
        "ExitCodePanel",
        "ExitCodeTextBlock",
        "DurationPanel",
        "DurationTextBlock",
        "RunStateBorder",
        "SshKeyPathPanel",
        "SshKeyPassphraseBox",
        "SshPasswordPanel"
    )) {
        $map[$name] = $Window.FindName($name)
    }

    return $map
}

function Get-NcsTreeViewSelection {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls,
        [Parameter(Mandatory)]
        [string] $TreeViewName
    )

    $selectedItem = $Controls[$TreeViewName].SelectedItem
    if ($null -eq $selectedItem -or [string]::IsNullOrWhiteSpace($selectedItem.Tag)) {
        return ""
    }
    return [string] $selectedItem.Tag
}

function Build-NcsTreeView {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls,
        [Parameter(Mandatory)]
        [string] $TreeViewName,
        [Parameter(Mandatory)]
        $Groups,
        [Parameter(Mandatory)]
        [string] $TagProperty,
        [bool] $Expanded = $true,
        [string] $LeafIcon = ""
    )

    $tree = $Controls[$TreeViewName]
    $tree.Items.Clear()
    foreach ($group in $Groups) {
        $groupItem = [System.Windows.Controls.TreeViewItem]::new()
        $groupItem.Header = $group.Group
        $groupItem.Tag = $group.Group
        $groupItem.IsExpanded = $Expanded
        foreach ($item in $group.Items) {
            $leafItem = [System.Windows.Controls.TreeViewItem]::new()
            $leafItem.Tag = $item[$TagProperty]

            if (-not [string]::IsNullOrWhiteSpace($LeafIcon)) {
                $sp = [System.Windows.Controls.StackPanel]::new()
                $sp.Orientation = "Horizontal"
                $icon = [System.Windows.Shapes.Path]::new()
                $icon.Data = [System.Windows.Media.Geometry]::Parse($LeafIcon)
                $icon.Stroke = Get-NcsBrush -Color "#8e939c"
                $icon.StrokeThickness = 1
                $icon.Fill = [System.Windows.Media.Brushes]::Transparent
                $icon.Width = 10
                $icon.Height = 10
                $icon.Stretch = [System.Windows.Media.Stretch]::Uniform
                $icon.VerticalAlignment = "Center"
                $icon.Margin = [System.Windows.Thickness]::new(0,0,5,0)
                $sp.Children.Add($icon) | Out-Null
                $tb = [System.Windows.Controls.TextBlock]::new()
                $tb.Text = $item.Label
                $tb.VerticalAlignment = "Center"
                $sp.Children.Add($tb) | Out-Null
                $leafItem.Header = $sp
            } else {
                $leafItem.Header = $item.Label
            }

            $groupItem.Items.Add($leafItem) | Out-Null
        }
        $tree.Items.Add($groupItem) | Out-Null
    }
}

function Select-NcsTreeViewItem {
    param(
        [Parameter(Mandatory)]
        [System.Windows.Controls.TreeView] $TreeView,
        [string] $Tag,
        [switch] $FallbackToFirst
    )

    if (-not [string]::IsNullOrWhiteSpace($Tag)) {
        foreach ($category in @($TreeView.Items)) {
            foreach ($leaf in @($category.Items)) {
                if ($leaf.Tag -eq $Tag) {
                    $leaf.IsSelected = $true
                    return
                }
            }
        }
    }

    if ($FallbackToFirst -and $TreeView.Items.Count -gt 0) {
        $firstCategory = $TreeView.Items[0]
        if ($null -ne $firstCategory -and $firstCategory.Items.Count -gt 0) {
            $firstCategory.Items[0].IsSelected = $true
        }
    }
}

function Update-NcsActionOptions {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls,
        [Parameter(Mandatory)]
        $ActionGroups,
        [string] $Playbook
    )

    $Controls.ActionOptionsPanel.Children.Clear()
    $Controls.ActionOptionsPanel.Visibility = "Collapsed"

    if ([string]::IsNullOrWhiteSpace($Playbook)) { return }

    $actionItem = $null
    foreach ($group in $ActionGroups) {
        foreach ($item in $group.Items) {
            if ($item['playbook'] -eq $Playbook -and $item.ContainsKey('options')) {
                $actionItem = $item
                break
            }
        }
        if ($null -ne $actionItem) { break }
    }

    if ($null -eq $actionItem) { return }

    $options = $actionItem['options']
    if ($null -eq $options -or @($options).Length -eq 0) { return }

    $Controls.ActionOptionsPanel.Visibility = "Visible"

    foreach ($opt in @($options)) {
        $label = [System.Windows.Controls.TextBlock]::new()
        $label.Text = $opt['label']
        $label.Foreground = Get-NcsBrush -Color "#8e939c"
        $label.FontSize = 11
        $Controls.ActionOptionsPanel.Children.Add($label) | Out-Null

        $textBox = [System.Windows.Controls.TextBox]::new()
        $textBox.Tag = $opt['name']
        if ($opt.ContainsKey('default')) { $textBox.Text = $opt['default'] }
        $Controls.ActionOptionsPanel.Children.Add($textBox) | Out-Null
    }
}

function Get-NcsActionOptionValues {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls
    )

    $values = @{}
    foreach ($child in @($Controls.ActionOptionsPanel.Children)) {
        if ($child -is [System.Windows.Controls.TextBox] -and -not [string]::IsNullOrWhiteSpace($child.Tag)) {
            $val = $child.Text.Trim()
            if (-not [string]::IsNullOrWhiteSpace($val)) {
                $values[$child.Tag] = $val
            }
        }
    }
    return $values
}

function Set-NcsRequestFromControls {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls,
        [Parameter(Mandatory)]
        [NcsActionRequest] $Request
    )

    $Request.Limit = $Controls.ActionLimitTextBox.Text.Trim()
    $Request.Tags = $Controls.ActionTagsTextBox.Text.Trim()
    $Request.CheckMode = $Controls.ActionCheckModeCheckBox.IsChecked
    $Request.Diff = $Controls.ActionDiffCheckBox.IsChecked
    $verbosity = [string] $Controls.ActionVerbosityComboBox.SelectedItem
    $Request.Verbosity = switch ($verbosity) {
        "Verbose"          { "-v" }
        "More Verbose"     { "-vv" }
        "Debug"            { "-vvv" }
        "Connection Debug" { "-vvvv" }
        default            { "" }
    }
    $Request.ExtraArgs = $Controls.ExtraArgsTextBox.Text.Trim()
    $Request.Options = Get-NcsActionOptionValues -Controls $Controls
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

    $path = [System.Windows.Shapes.Path]::new()
    $path.Width = 10
    $path.Height = 10
    $path.Stretch = [System.Windows.Media.Stretch]::Fill
    $path.Stroke = Get-NcsBrush -Color "#8e939c"
    $path.StrokeThickness = 1.5
    $path.Fill = [System.Windows.Media.Brushes]::Transparent

    if ($Window.WindowState -eq [System.Windows.WindowState]::Maximized) {
        $path.Data = [System.Windows.Media.Geometry]::Parse("M2 0 L10 0 L10 8 L8 8 L8 10 L0 10 L0 2 L2 2 Z")
    }
    else {
        $path.Data = [System.Windows.Media.Geometry]::Parse("M0 0 L10 0 L10 10 L0 10 Z")
    }
    $Controls.MaximizeWindowButton.Content = $path
}

function Update-NcsTopTabState {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls
    )

    $Controls.SettingsToggleButton.Tag = if ($Controls.SettingsPanel.Visibility -eq "Visible") { "Active" } else { "Inactive" }
    $Controls.OperateToggleButton.Tag = if ($Controls.OperateContent.Visibility -eq "Visible") { "Active" } else { "Inactive" }
    $Controls.ConsoleShowButton.Tag = if ($Controls.ConsolePane.Visibility -eq "Visible") { "Active" } else { "Inactive" }
    $Controls.ReportsToggleButton.Tag = if ($Controls.ReportsPane.Visibility -eq "Visible") { "Active" } else { "Inactive" }
}

function Set-NcsPreflightState {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls,
        [Parameter(Mandatory)]
        [string] $State
    )

    if ($State -eq "Connected") {
        $Controls.PreflightButtonText.Text = "Disconnect"
        $Controls.PreflightButton.Background = Get-NcsBrush -Color "#16825d"
        $Controls.PreflightButton.ToolTip = "Disconnect from remote host"
    } else {
        $Controls.PreflightButtonText.Text = "Connect"
        $Controls.PreflightButton.Background = Get-NcsBrush -Color "#6e9fff"
        $Controls.PreflightButton.ToolTip = "Connect to remote host"
    }
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
        [NcsConsoleSettings] $Settings
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
    $Settings.SshKeyPassphrase = $Controls.SshKeyPassphraseBox.Password
    $Settings.SshPassword = $Controls.SshPasswordBox.Password
    $Settings.RemoteRepoPath = $Controls.RemoteRepoPathTextBox.Text.Trim()
    $Settings.LastAction = Get-NcsTreeViewSelection -Controls $Controls -TreeViewName "ActionTreeView"
}

function Sync-NcsControlsFromSettings {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls,
        [Parameter(Mandatory)]
        [NcsConsoleSettings] $Settings
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
    $Controls.SshKeyPassphraseBox.Password = $Settings.SshKeyPassphrase
    $Controls.SshPasswordBox.Password = $Settings.SshPassword
    $Controls.RemoteRepoPathTextBox.Text = $Settings.RemoteRepoPath
    Select-NcsTreeViewItem -TreeView $Controls.ActionTreeView -Tag $Settings.LastAction -FallbackToFirst

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

    $Controls.RunButton.Visibility = "Visible"
    $Controls.CancelButton.Visibility = "Collapsed"
}

function Set-NcsRunningUiState {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls
    )

    $Controls.RunButton.Visibility = "Collapsed"
    $Controls.CancelButton.Visibility = "Visible"
    $Controls.RunStateBorder.Visibility = "Visible"
    $Controls.ExitCodePanel.Visibility = "Visible"
    $Controls.DurationPanel.Visibility = "Visible"
}

function Update-NcsCommandPreview {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls,
        [Parameter(Mandatory)]
        [NcsConsoleSettings] $Settings
    )

    $playbook = Get-NcsTreeViewSelection -Controls $Controls -TreeViewName "ActionTreeView"

    if (-not [string]::IsNullOrWhiteSpace($playbook)) {
        try {
            $request = [NcsActionRequest]::new($playbook)
            Set-NcsRequestFromControls -Controls $Controls -Request $request
            $preview = Resolve-NcsPlaybookCommand -Settings $Settings -Request $request
            $Controls.CommandPreviewTextBox.Text = $preview
        } catch {
            $Controls.CommandPreviewTextBox.Text = ""
        }
    } else {
        $Controls.CommandPreviewTextBox.Text = ""
    }

    Update-NcsSshAuthVisibility -Controls $Controls -AuthMode ([string] $Controls.SshAuthModeComboBox.SelectedItem)
    Update-NcsConnectionInfo -Controls $Controls
}

function Format-NcsDuration {
    param(
        [timespan] $Duration
    )

    return $Duration.ToString("hh\:mm\:ss")
}

function Show-NcsConsoleApp {
    param(
        [Parameter(Mandatory)]
        [string] $ProjectRoot
    )

    Import-NcsWpfAssemblies

    $xamlPath = Join-Path -Path $ProjectRoot -ChildPath "App/MainWindow.xaml"
    $resourceXamlPath = Join-Path -Path $ProjectRoot -ChildPath "App/MainWindow.Resources.xaml"
    $xamlText = Get-Content -LiteralPath $xamlPath -Raw
    $resourceXamlText = Get-Content -LiteralPath $resourceXamlPath -Raw
    $xamlText = $xamlText.Replace("<!-- @@MAIN_WINDOW_RESOURCES@@ -->", $resourceXamlText)
    [xml] $xaml = $xamlText
    $reader = [System.Xml.XmlNodeReader]::new($xaml)
    $window = [Windows.Markup.XamlReader]::Load($reader)
    $controls = Get-NcsXamlControlMap -Window $window

    $state = [pscustomobject]@{
        Settings        = (Import-NcsConsoleSettings)
        PreflightResult = $null
        CurrentHandle   = $null
        LastRunResult   = $null
        ReportCacheRoot = $(if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
                Join-Path -Path $env:LOCALAPPDATA -ChildPath "NcsConsole/ReportCache/reports"
            } else {
                Join-Path -Path ([System.IO.Path]::GetTempPath()) -ChildPath "NcsConsole/ReportCache/reports"
            })
    }

    $script:ActionGroups = @()
    $actionConfigPath = Join-Path -Path $ProjectRoot -ChildPath "Config/actions.yml"

    $controls.ActionVerbosityComboBox.ItemsSource = @("Normal", "Verbose", "More Verbose", "Debug", "Connection Debug")
    $controls.ActionVerbosityComboBox.SelectedIndex = 0

    Sync-NcsControlsFromSettings -Controls $controls -Settings $state.Settings
    Set-NcsIdleUiState -Controls $controls
    $controls.StatusTextBlock.Text = "Ready."
    Set-NcsRunStateBadge -Controls $controls -State "Idle"
    Set-NcsPreflightState -Controls $controls -State "Not Connected"
    $controls.RunMetaText.Text = ""

    Update-NcsWindowChromeState -Window $window -Controls $controls
    Update-NcsTopTabState -Controls $controls
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

    $invalidatePreflight = {
        $state.PreflightResult = $null
        Set-NcsPreflightState -Controls $controls -State "Not Connected"
    }

    & $refreshPreview

    $controls.ActionTreeView.Add_PreviewMouseWheel({
        param($s, $e)
        $controls.ActionScrollViewer.ScrollToVerticalOffset($controls.ActionScrollViewer.VerticalOffset - $e.Delta / 3)
        $e.Handled = $true
    })

    $controls.ActionTreeView.Add_SelectedItemChanged({
        param($s, $e)
        $item = $e.NewValue
        $playbook = ""
        $label = "Select a playbook"
        if ($null -ne $item -and -not [string]::IsNullOrWhiteSpace($item.Tag)) {
            $state.Settings.LastAction = $item.Tag
            $playbook = $item.Tag
            if ($item.Header -is [System.Windows.Controls.StackPanel]) {
                foreach ($child in @($item.Header.Children)) {
                    if ($child -is [System.Windows.Controls.TextBlock]) {
                        $label = $child.Text
                        break
                    }
                }
            } else {
                $label = [string] $item.Header
            }
        }
        $controls.ActionSelectionTitle.Text = $label
        $controls.ActionPropertiesPanel.Visibility = if ([string]::IsNullOrWhiteSpace($playbook)) { "Collapsed" } else { "Visible" }
        $isMutating = $false
        if (-not [string]::IsNullOrWhiteSpace($playbook)) {
            foreach ($group in $script:ActionGroups) {
                foreach ($actionItem in $group.Items) {
                    if ($actionItem['playbook'] -eq $playbook -and $actionItem.ContainsKey('mutating') -and $actionItem['mutating'] -eq $true) {
                        $isMutating = $true
                        break
                    }
                }
                if ($isMutating) { break }
            }
        }
        $controls.MutatingWarning.Visibility = if ($isMutating) { "Visible" } else { "Collapsed" }
        Update-NcsActionOptions -Controls $controls -ActionGroups $script:ActionGroups -Playbook $playbook
        & $refreshPreview
    })

    $controls.ActionLimitTextBox.Add_TextChanged({ & $refreshPreview })
    $getSelectedTag = {
        $item = $controls.ActionLimitTree.SelectedItem
        if ($null -eq $item -or [string]::IsNullOrWhiteSpace($item.Tag)) { return $null }
        return [string] $item.Tag
    }

    $appendToLimit = {
        param([string] $Value)
        $current = $controls.ActionLimitTextBox.Text.Trim()
        if ([string]::IsNullOrWhiteSpace($current)) {
            $controls.ActionLimitTextBox.Text = $Value
        } else {
            $controls.ActionLimitTextBox.Text = "$current,$Value"
        }
    }

    $removeFromLimit = {
        $tag = & $getSelectedTag
        if (-not $tag) { return }
        $current = $controls.ActionLimitTextBox.Text.Trim()
        $parts = @($current -split ',' | ForEach-Object { $_.Trim() } | Where-Object {
            $_ -ne '' -and $_ -ne $tag -and $_ -ne "!$tag" -and $_ -ne ":&$tag" -and $_ -ne "$tag*"
        })
        $controls.ActionLimitTextBox.Text = $parts -join ','
    }

    $isInLimit = {
        param([string] $Tag)
        $current = $controls.ActionLimitTextBox.Text.Trim()
        $parts = @($current -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
        return ($parts -contains $Tag -or $parts -contains "!$Tag" -or $parts -contains ":&$Tag" -or $parts -contains "$Tag*")
    }

    $newMenuItem = {
        param([string] $Header, [scriptblock] $Action)
        $item = [System.Windows.Controls.MenuItem]::new()
        $item.Header = $Header
        $item.Background = Get-NcsBrush -Color "#1e2228"
        $item.Foreground = Get-NcsBrush -Color "#d8dce2"
        $item.Margin = [System.Windows.Thickness]::new(0)
        $item.Padding = [System.Windows.Thickness]::new(10,5,10,5)
        $item.Template = [System.Windows.Markup.XamlReader]::Parse(
            '<ControlTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" TargetType="MenuItem">' +
            '<Border x:Name="Bd" Background="{TemplateBinding Background}" Padding="{TemplateBinding Padding}">' +
            '<ContentPresenter ContentSource="Header" />' +
            '</Border>' +
            '<ControlTemplate.Triggers>' +
            '<Trigger Property="IsHighlighted" Value="True"><Setter TargetName="Bd" Property="Background" Value="#242932" /></Trigger>' +
            '<Trigger Property="IsEnabled" Value="False"><Setter Property="Foreground" Value="#555a65" /></Trigger>' +
            '</ControlTemplate.Triggers>' +
            '</ControlTemplate>'
        )
        $a = $Action
        $item.Add_Click({ & $a }.GetNewClosure())
        return $item
    }

    $limitContextMenu = [System.Windows.Controls.ContextMenu]::new()
    $limitContextMenu.Template = [System.Windows.Markup.XamlReader]::Parse(
        '<ControlTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" TargetType="ContextMenu">' +
        '<Border Background="#1e2228" BorderBrush="#2c3038" BorderThickness="1" Padding="0" MinWidth="140">' +
        '<StackPanel IsItemsHost="True" KeyboardNavigation.DirectionalNavigation="Cycle" />' +
        '</Border>' +
        '</ControlTemplate>'
    )

    $newSep = {
        $sep = [System.Windows.Controls.Separator]::new()
        $sep.Template = [System.Windows.Markup.XamlReader]::Parse(
            '<ControlTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" TargetType="Separator">' +
            '<Border Height="1" Background="#2c3038" Margin="4,2,4,2" />' +
            '</ControlTemplate>'
        )
        return $sep
    }

    $addItem = & $newMenuItem "Add" { $tag = & $getSelectedTag; if ($tag) { & $appendToLimit $tag } }
    $removeItem = & $newMenuItem "Remove" { & $removeFromLimit }
    $limitContextMenu.Items.Add($addItem) | Out-Null
    $limitContextMenu.Items.Add($removeItem) | Out-Null
    $limitContextMenu.Items.Add((& $newSep)) | Out-Null
    $limitContextMenu.Items.Add((& $newMenuItem "Exclude (!)" { $tag = & $getSelectedTag; if ($tag) { & $appendToLimit "!$tag" } })) | Out-Null
    $limitContextMenu.Items.Add((& $newMenuItem "Intersect (:&)" { $tag = & $getSelectedTag; if ($tag) { & $appendToLimit ":&$tag" } })) | Out-Null
    $limitContextMenu.Items.Add((& $newMenuItem "Wildcard (*)" { $tag = & $getSelectedTag; if ($tag) { & $appendToLimit "$tag*" } })) | Out-Null
    $limitContextMenu.Items.Add((& $newSep)) | Out-Null
    $limitContextMenu.Items.Add((& $newMenuItem "Clear all" { $controls.ActionLimitTextBox.Text = "" })) | Out-Null

    $limitContextMenu.Add_Opened({
        $pos = [System.Windows.Input.Mouse]::GetPosition($controls.ActionLimitTree)
        $hit = [System.Windows.Media.VisualTreeHelper]::HitTest($controls.ActionLimitTree, $pos)
        if ($null -ne $hit -and $null -ne $hit.VisualHit) {
            $element = $hit.VisualHit
            while ($null -ne $element -and $element -isnot [System.Windows.Controls.TreeViewItem]) {
                $element = [System.Windows.Media.VisualTreeHelper]::GetParent($element)
            }
            if ($null -ne $element) {
                $element.IsSelected = $true
            }
        }
        $tag = & $getSelectedTag
        $inLimit = if ($tag) { & $isInLimit $tag } else { $false }
        $removeItem.IsEnabled = $inLimit
    })

    $controls.ActionLimitTree.ContextMenu = $limitContextMenu

    $controls.ActionLimitTree.Add_PreviewMouseWheel({
        param($s, $e)
        $controls.ActionLimitTreeScroll.ScrollToVerticalOffset($controls.ActionLimitTreeScroll.VerticalOffset - $e.Delta / 3)
        $e.Handled = $true
    })
    $controls.ActionTagsTextBox.Add_TextChanged({ & $refreshPreview })
    $controls.ActionCheckModeCheckBox.Add_Checked({ & $refreshPreview })
    $controls.ActionCheckModeCheckBox.Add_Unchecked({ & $refreshPreview })
    $controls.ActionDiffCheckBox.Add_Checked({ & $refreshPreview })
    $controls.ActionDiffCheckBox.Add_Unchecked({ & $refreshPreview })
    $controls.ActionVerbosityComboBox.Add_SelectionChanged({ & $refreshPreview })
    $controls.ExtraArgsTextBox.Add_TextChanged({ & $refreshPreview })
    $controls.SshHostTextBox.Add_TextChanged({ & $invalidatePreflight; & $refreshPreview })
    $controls.SshPortTextBox.Add_TextChanged({ & $invalidatePreflight; & $refreshPreview })
    $controls.SshUserTextBox.Add_TextChanged({ & $invalidatePreflight; & $refreshPreview })
    $controls.SshAuthModeComboBox.Add_SelectionChanged({ & $invalidatePreflight; & $refreshPreview })
    $controls.SshKeyPathTextBox.Add_TextChanged({ & $invalidatePreflight; & $refreshPreview })
    $controls.SshKeyPassphraseBox.Add_PasswordChanged({ & $invalidatePreflight; & $refreshPreview })
    $controls.SshPasswordBox.Add_PasswordChanged({ & $invalidatePreflight; & $refreshPreview })
    $controls.RemoteRepoPathTextBox.Add_TextChanged({ & $invalidatePreflight; & $refreshPreview })

    $controls.SaveSettingsButton.Add_Click({
        try {
            Sync-NcsSettingsFromControls -Controls $controls -Settings $state.Settings
            Save-NcsConsoleSettings -Settings $state.Settings
            $controls.StatusTextBlock.Text = "Settings saved to $(Get-NcsConsoleSettingsPath)."
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
        param($s, $e)

        if ($e.ClickCount -eq 2) {
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
        $settingsColumn.Width = [System.Windows.GridLength]::new(1, [System.Windows.GridUnitType]::Star)
        $settingsColumn.MinWidth = 0
        $controls.SettingsPanel.Visibility = "Visible"
        $controls.SettingsSplitter.Visibility = "Visible"
        Update-NcsTopTabState -Controls $controls
    }

    $closeSettings = {
        $controls.SettingsPanel.Visibility = "Collapsed"
        $controls.SettingsSplitter.Visibility = "Collapsed"
        $settingsColumn.Width = [System.Windows.GridLength]::new(0)
        $settingsColumn.MinWidth = 0
        Update-NcsTopTabState -Controls $controls
    }

    $controls.SettingsToggleButton.Add_Click({
        if ($controls.SettingsPanel.Visibility -eq "Visible") {
            & $closeSettings
        } else {
            & $openSettings
        }
    })

    $controls.SettingsCloseButton.Add_Click({ & $closeSettings })

    $operateColumn = $controls.OperatePanel.ColumnDefinitions[2]

    $openOperate = {
        $operateColumn.Width = [System.Windows.GridLength]::new(1, [System.Windows.GridUnitType]::Star)
        $operateColumn.MinWidth = 0
        $controls.OperateContent.Visibility = "Visible"
        Update-NcsTopTabState -Controls $controls
    }

    $closeOperate = {
        $controls.OperateContent.Visibility = "Collapsed"
        $operateColumn.Width = [System.Windows.GridLength]::new(0)
        $operateColumn.MinWidth = 0
        Update-NcsTopTabState -Controls $controls
    }

    $controls.OperateToggleButton.Add_Click({
        if ($controls.OperateContent.Visibility -eq "Visible") {
            & $closeOperate
        } else {
            & $openOperate
        }
    })

    $consoleColumn = $controls.OperatePanel.ColumnDefinitions[4]

    $openConsole = {
        $consoleColumn.Width = [System.Windows.GridLength]::new(1, [System.Windows.GridUnitType]::Star)
        $consoleColumn.MinWidth = 0
        $controls.ConsolePane.Visibility = "Visible"
        $controls.ConsoleSplitter.Visibility = "Visible"
        Update-NcsTopTabState -Controls $controls
    }

    $closeConsole = {
        $controls.ConsolePane.Visibility = "Collapsed"
        $controls.ConsoleSplitter.Visibility = "Collapsed"
        $consoleColumn.Width = [System.Windows.GridLength]::new(0)
        $consoleColumn.MinWidth = 0
        Update-NcsTopTabState -Controls $controls
    }

    $controls.ConsoleToggleButton.Add_Click({ & $closeConsole })

    $controls.ConsoleShowButton.Add_Click({
        if ($controls.ConsolePane.Visibility -eq "Visible") {
            & $closeConsole
        } else {
            & $openConsole
        }
    })

    $reportsColumn = $controls.OperatePanel.ColumnDefinitions[6]
    $script:ReportHistory = [System.Collections.Generic.List[string]]::new()
    $script:CurrentReportPath = ""

    $loadReport = {
        param([string] $RelativePath)
        if (-not $state.PreflightResult -or -not $state.PreflightResult.IsReady) { return }
        try {
            $mirror = Invoke-NcsReportMirror -Settings $state.Settings -LocalRoot $state.ReportCacheRoot
            if ($mirror.ExitCode -eq 0) {
                $localReportPath = Join-Path -Path $state.ReportCacheRoot -ChildPath ($RelativePath -replace '/', [System.IO.Path]::DirectorySeparatorChar)
                if (-not (Test-Path -LiteralPath $localReportPath)) {
                    $controls.ReportPlaceholder.Text = "Report not found after sync: $RelativePath"
                    return
                }

                if (-not [string]::IsNullOrWhiteSpace($script:CurrentReportPath) -and $script:CurrentReportPath -ne $RelativePath) {
                    $script:ReportHistory.Add($script:CurrentReportPath)
                }
                $script:CurrentReportPath = $RelativePath
                $controls.ReportBackButton.IsEnabled = $script:ReportHistory.Count -gt 0
                $controls.ReportPlaceholder.Text = "Opened report in default browser: $RelativePath"
                Start-Process -FilePath $localReportPath | Out-Null
                return
            }

            $message = @($mirror.StdErr, $mirror.StdOut) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -First 1
            if ([string]::IsNullOrWhiteSpace($message)) { $message = "scp.exe failed to mirror reports." }
            $controls.ReportPlaceholder.Text = $message.Trim()
        } catch {
            $controls.ReportPlaceholder.Text = $_.Exception.Message
        }
    }

    $openReports = {
        $reportsColumn.Width = [System.Windows.GridLength]::new(1, [System.Windows.GridUnitType]::Star)
        $reportsColumn.MinWidth = 0
        $controls.ReportsPane.Visibility = "Visible"
        $controls.ReportsSplitter.Visibility = "Visible"
        Update-NcsTopTabState -Controls $controls
        if ([string]::IsNullOrWhiteSpace($script:CurrentReportPath) -and $state.PreflightResult -and $state.PreflightResult.IsReady) {
            & $loadReport "site_health_report.html"
        }
    }

    $closeReports = {
        $controls.ReportsPane.Visibility = "Collapsed"
        $controls.ReportsSplitter.Visibility = "Collapsed"
        $reportsColumn.Width = [System.Windows.GridLength]::new(0)
        $reportsColumn.MinWidth = 0
        Update-NcsTopTabState -Controls $controls
    }

    $controls.ReportsCloseButton.Add_Click({ & $closeReports })

    $controls.ReportsToggleButton.Add_Click({
        if ($controls.ReportsPane.Visibility -eq "Visible") {
            & $closeReports
        } else {
            & $openReports
        }
    })

    $controls.ReportHomeButton.Add_Click({
        & $loadReport "site_health_report.html"
    })

    $controls.ReportBackButton.Add_Click({
        if ($script:ReportHistory.Count -gt 0) {
            $prev = $script:ReportHistory[$script:ReportHistory.Count - 1]
            $script:ReportHistory.RemoveAt($script:ReportHistory.Count - 1)
            $script:CurrentReportPath = ""
            & $loadReport $prev
        }
    })

    $controls.ReportRefreshButton.Add_Click({
        if (-not [string]::IsNullOrWhiteSpace($script:CurrentReportPath)) {
            $path = $script:CurrentReportPath
            $script:CurrentReportPath = ""
            & $loadReport $path
        }
    })

    $controls.PreflightButton.Add_Click({
        try {
            if ($null -ne $state.PreflightResult -and $state.PreflightResult.IsReady) {
                $state.PreflightResult = $null
                Set-NcsPreflightState -Controls $controls -State "Not Connected"
                $controls.ConnectionInfoText.Text = ""
                $controls.StatusTextBlock.Text = "Disconnected."
                $controls.ActionLimitTreeBorder.Visibility = "Collapsed"
                $controls.PlaybookSplitPane.Visibility = "Collapsed"
                $controls.PlaybookPlaceholder.Visibility = "Visible"
                $controls.RefreshPlaybooksButton.Visibility = "Collapsed"
                $controls.ReportPlaceholder.Text = "Connect to sync reports and open them in your browser"
                $script:ReportHistory.Clear()
                $script:CurrentReportPath = ""
                $controls.ReportBackButton.IsEnabled = $false
                return
            }

            Sync-NcsSettingsFromControls -Controls $controls -Settings $state.Settings

            if ($state.Settings.SshAuthMode -eq [NcsSshAuthMode]::KeyFile.ToString()) {
                $inputBox = [System.Windows.Window]::new()
                $inputBox.Title = ""
                $inputBox.Width = 350
                $inputBox.SizeToContent = "Height"
                $inputBox.WindowStartupLocation = "CenterOwner"
                $inputBox.Owner = $window
                $inputBox.WindowStyle = "None"
                $inputBox.ResizeMode = "NoResize"
                $inputBox.Background = Get-NcsBrush -Color "#181b1f"
                $inputBox.BorderBrush = Get-NcsBrush -Color "#2c3038"
                $inputBox.BorderThickness = [System.Windows.Thickness]::new(1)
                $sp = [System.Windows.Controls.StackPanel]::new()
                $sp.Margin = [System.Windows.Thickness]::new(16)
                $title = [System.Windows.Controls.TextBlock]::new()
                $title.Text = "SSH Key Passphrase"
                $title.Foreground = Get-NcsBrush -Color "#d8dce2"
                $title.FontSize = 14
                $title.FontWeight = "Bold"
                $title.Margin = [System.Windows.Thickness]::new(0,0,0,8)
                $sp.Children.Add($title) | Out-Null
                $label = [System.Windows.Controls.TextBlock]::new()
                $label.Text = "Enter passphrase for SSH key (leave empty if none):"
                $label.Foreground = Get-NcsBrush -Color "#8e939c"
                $label.Margin = [System.Windows.Thickness]::new(0,0,0,6)
                $label.TextWrapping = "Wrap"
                $label.FontSize = 11
                $sp.Children.Add($label) | Out-Null
                $pwBox = [System.Windows.Controls.PasswordBox]::new()
                $pwBox.Background = Get-NcsBrush -Color "#1e2228"
                $pwBox.Foreground = Get-NcsBrush -Color "#d8dce2"
                $pwBox.BorderBrush = Get-NcsBrush -Color "#2c3038"
                $pwBox.CaretBrush = Get-NcsBrush -Color "#d8dce2"
                $pwBox.Padding = [System.Windows.Thickness]::new(8,5,8,5)
                $sp.Children.Add($pwBox) | Out-Null
                $btnPanel = [System.Windows.Controls.StackPanel]::new()
                $btnPanel.Orientation = "Horizontal"
                $btnPanel.HorizontalAlignment = "Right"
                $btnPanel.Margin = [System.Windows.Thickness]::new(0,10,0,0)
                $okBtn = [System.Windows.Controls.Button]::new()
                $okBtn.Content = "Connect"
                $okBtn.Background = Get-NcsBrush -Color "#1e2228"
                $okBtn.Foreground = Get-NcsBrush -Color "#d8dce2"
                $okBtn.BorderBrush = Get-NcsBrush -Color "#2c3038"
                $okBtn.Padding = [System.Windows.Thickness]::new(12,5,12,5)
                $okBtn.Margin = [System.Windows.Thickness]::new(6,0,0,0)
                $okBtn.IsDefault = $true
                $okBtn.Add_Click({ $inputBox.DialogResult = $true })
                $cancelBtn = [System.Windows.Controls.Button]::new()
                $cancelBtn.Content = "Cancel"
                $cancelBtn.Background = Get-NcsBrush -Color "#1e2228"
                $cancelBtn.Foreground = Get-NcsBrush -Color "#8e939c"
                $cancelBtn.BorderBrush = Get-NcsBrush -Color "#2c3038"
                $cancelBtn.Padding = [System.Windows.Thickness]::new(12,5,12,5)
                $cancelBtn.Add_Click({ $inputBox.DialogResult = $false })
                $btnPanel.Children.Add($cancelBtn) | Out-Null
                $btnPanel.Children.Add($okBtn) | Out-Null
                $sp.Children.Add($btnPanel) | Out-Null
                $inputBox.Content = $sp
                $pwBox.Focus() | Out-Null

                $result = $inputBox.ShowDialog()
                if ($result -ne $true) {
                    $controls.StatusTextBlock.Text = "Connection cancelled."
                    return
                }
                $state.Settings.SshKeyPassphrase = $pwBox.Password
                $controls.SshKeyPassphraseBox.Password = $pwBox.Password
            }

            $controls.StatusTextBlock.Text = "Connecting..."
            $preflight = Test-NcsRemotePreflight -Settings $state.Settings
            $state.PreflightResult = $preflight
            if ($preflight.IsReady) {
                Set-NcsPreflightState -Controls $controls -State "Connected"
                if (-not [string]::IsNullOrWhiteSpace($preflight.Banner)) {
                    $controls.ConsoleTextBox.AppendText($preflight.Banner + [Environment]::NewLine + [Environment]::NewLine)
                }
                $statusParts = @("Connected.")
                try {
                    $inventoryTree = Get-NcsRemoteInventoryTree -Settings $state.Settings
                    if (@($inventoryTree).Length -gt 0) {
                        Build-NcsTreeView -Controls $controls -TreeViewName "ActionLimitTree" -Groups $inventoryTree -TagProperty "limit" -Expanded $false -LeafIcon "M1 3 L5 3 L5 1 L11 1 L11 3 L15 3 L15 13 L1 13 Z"
                        $controls.ActionLimitTreeBorder.Visibility = "Visible"
                        $statusParts += "$(@($inventoryTree).Length) inventory groups."
                    }
                } catch {
                    $statusParts += "Inventory fetch failed."
                }
                try {
                    $localConfig = @()
                    try { $localConfig = Import-NcsGroupedConfig -Path $actionConfigPath } catch {}
                    $remotePlaybooks = Get-NcsRemotePlaybookTree -Settings $state.Settings
                    if (@($localConfig).Length -gt 0 -and @($remotePlaybooks).Length -gt 0) {
                        $script:ActionGroups = Merge-NcsActionGroups -ConfigGroups $localConfig -RemoteGroups $remotePlaybooks
                    } elseif (@($remotePlaybooks).Length -gt 0) {
                        $script:ActionGroups = $remotePlaybooks
                    } elseif (@($localConfig).Length -gt 0) {
                        $script:ActionGroups = $localConfig
                        $statusParts += "Playbook scan empty, using local config."
                    } else {
                        $script:ActionGroups = @()
                        $statusParts += "No playbooks found."
                    }
                } catch {
                    try {
                        $script:ActionGroups = Import-NcsGroupedConfig -Path $actionConfigPath
                        $statusParts += "Playbook scan failed, using local config."
                    } catch {
                        $script:ActionGroups = @()
                        $statusParts += "Playbook scan failed, no local config available."
                    }
                }
                Build-NcsTreeView -Controls $controls -TreeViewName "ActionTreeView" -Groups $script:ActionGroups -TagProperty "playbook" -Expanded $true -LeafIcon "M2 0 L8 0 L10 2 L10 14 L2 14 Z M4 4 L8 4 M4 7 L8 7 M4 10 L7 10"
                $controls.PlaybookPlaceholder.Visibility = "Collapsed"
                $controls.PlaybookSplitPane.Visibility = "Visible"
                $controls.RefreshPlaybooksButton.Visibility = "Visible"
                Select-NcsTreeViewItem -TreeView $controls.ActionTreeView -Tag $state.Settings.LastAction -FallbackToFirst
                $controls.StatusTextBlock.Text = $statusParts -join " "
            } else {
                $controls.StatusTextBlock.Text = ($preflight.BlockingIssues -join " | ")
                Set-NcsPreflightState -Controls $controls -State "Failed"
            }
        } catch {
            $controls.StatusTextBlock.Text = $_.Exception.Message
            Set-NcsPreflightState -Controls $controls -State "Failed"
        }
    })

    $controls.RefreshPlaybooksButton.Add_Click({
        if (-not $state.PreflightResult -or -not $state.PreflightResult.IsReady) { return }
        try {
            $controls.StatusTextBlock.Text = "Refreshing..."
            $selectedPlaybook = Get-NcsTreeViewSelection -Controls $controls -TreeViewName "ActionTreeView"
            try {
                $inventoryTree = Get-NcsRemoteInventoryTree -Settings $state.Settings
                if (@($inventoryTree).Length -gt 0) {
                    Build-NcsTreeView -Controls $controls -TreeViewName "ActionLimitTree" -Groups $inventoryTree -TagProperty "limit" -Expanded $false -LeafIcon "M1 3 L5 3 L5 1 L11 1 L11 3 L15 3 L15 13 L1 13 Z"
                    $controls.ActionLimitTreeBorder.Visibility = "Visible"
                }
            } catch {
                Add-NcsConsoleLine -Controls $controls -Line "Inventory refresh failed: $($_.Exception.Message)"
            }
            try {
                $localConfig = @()
                try { $localConfig = Import-NcsGroupedConfig -Path $actionConfigPath } catch {}
                $remotePlaybooks = Get-NcsRemotePlaybookTree -Settings $state.Settings
                if (@($localConfig).Length -gt 0 -and @($remotePlaybooks).Length -gt 0) {
                    $script:ActionGroups = Merge-NcsActionGroups -ConfigGroups $localConfig -RemoteGroups $remotePlaybooks
                } elseif (@($remotePlaybooks).Length -gt 0) {
                    $script:ActionGroups = $remotePlaybooks
                } elseif (@($localConfig).Length -gt 0) {
                    $script:ActionGroups = $localConfig
                }
            } catch {
                Add-NcsConsoleLine -Controls $controls -Line "Playbook refresh failed: $($_.Exception.Message)"
            }
            Build-NcsTreeView -Controls $controls -TreeViewName "ActionTreeView" -Groups $script:ActionGroups -TagProperty "playbook" -Expanded $true -LeafIcon "M2 0 L8 0 L10 2 L10 14 L2 14 Z M4 4 L8 4 M4 7 L8 7 M4 10 L7 10"
            Select-NcsTreeViewItem -TreeView $controls.ActionTreeView -Tag $selectedPlaybook -FallbackToFirst
            $controls.StatusTextBlock.Text = "Refreshed."
        } catch {
            $controls.StatusTextBlock.Text = "Refresh failed: $($_.Exception.Message)"
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
            $controls.DetectedPathsPanel.Visibility = "Collapsed"
            $controls.ExitCodeTextBlock.Text = "-"
            $controls.DurationTextBlock.Text = "-"
            Set-NcsRunStateBadge -Controls $controls -State "Running"
            $selectedPlaybook = Get-NcsTreeViewSelection -Controls $controls -TreeViewName "ActionTreeView"
            if ([string]::IsNullOrWhiteSpace($selectedPlaybook)) {
                throw "Select an action before running."
            }
            $controls.RunMetaText.Text = $selectedPlaybook
            $controls.StatusTextBlock.Text = "Starting remote command."
            Set-NcsRunningUiState -Controls $controls
            if ($controls.ConsolePane.Visibility -eq "Collapsed") {
                & $openConsole
            }

            $request = [NcsActionRequest]::new($selectedPlaybook)
            Set-NcsRequestFromControls -Controls $controls -Request $request
            $handle = Start-NcsRemoteCommand -Settings $state.Settings -Request $request `
                -OnOutput {
                    param($line)
                    if ($window.Dispatcher.CheckAccess()) {
                        Add-NcsConsoleLine -Controls $controls -Line $line
                    } else {
                        [void] $window.Dispatcher.BeginInvoke([action]{
                            Add-NcsConsoleLine -Controls $controls -Line $line
                        })
                    }
                } `
                -OnCompleted {
                    param($runResult)
                    $updateUi = [action]{
                        $durationTimer.Stop()
                        $state.LastRunResult = $runResult
                        $state.CurrentHandle = $null
                        Set-NcsIdleUiState -Controls $controls
                        Set-NcsRunStateBadge -Controls $controls -State $(if ($runResult.Succeeded) { "Succeeded" } else { "Failed" })
                        $controls.RunMetaText.Text = $runResult.Action
                        $controls.StatusTextBlock.Text = if ($runResult.Succeeded) { "Run completed successfully." } else { "Run failed." }
                        $controls.ExitCodeTextBlock.Text = [string] $runResult.ExitCode
                        $controls.DurationTextBlock.Text = Format-NcsDuration -Duration $runResult.Duration
                        $controls.DetectedPathsListBox.ItemsSource = $runResult.DetectedPaths
                        if ($null -ne $runResult.DetectedPaths -and @($runResult.DetectedPaths).Length -gt 0) {
                            $controls.DetectedPathsPanel.Visibility = "Visible"
                        }
                    }
                    if ($window.Dispatcher.CheckAccess()) {
                        & $updateUi
                    } else {
                        [void] $window.Dispatcher.BeginInvoke($updateUi)
                    }
                }
            $state.CurrentHandle = $handle
            $controls.CommandPreviewTextBox.Text = Resolve-NcsPlaybookCommand -Settings $state.Settings -Request $request
            $controls.CommandPreviewTextBox.Visibility = "Visible"
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
        $dialog.FileName = "ncs-console-$actionTag-$timestamp.txt"
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
