Set-StrictMode -Version Latest

$script:NcsWebView2Available = $false
$script:NcsWebView2Status = "WebView2 app dependencies are not installed."

$script:BrushConverter = $null
$script:BrushCache = @{}
$script:_NcsTreeViewItemStyle = $null
$script:IconFolder = "M1 3 L5 3 L5 1 L11 1 L11 3 L15 3 L15 13 L1 13 Z"
$script:IconFile = "M2 0 L8 0 L10 2 L10 14 L2 14 Z M4 4 L8 4 M4 7 L8 7 M4 10 L7 10"
$script:DefaultReportPath = "site_health_report.html"
function Get-NcsBrush {
    param([string] $Color)
    $cached = $script:BrushCache[$Color]
    if ($null -ne $cached) { return $cached }
    if ($null -eq $script:BrushConverter) {
        $script:BrushConverter = [System.Windows.Media.BrushConverter]::new()
    }
    $brush = $script:BrushConverter.ConvertFromString($Color)
    $brush.Freeze()
    $script:BrushCache[$Color] = $brush
    return $brush
}

$script:NcsLimitPickers = @{}

function Get-NcsLimitPickerContext {
    param([Parameter(Mandatory)] $Tree)
    return $script:NcsLimitPickers[[System.Runtime.CompilerServices.RuntimeHelpers]::GetHashCode($Tree)]
}

function Get-NcsLimitPickerSelectedTag {
    param([Parameter(Mandatory)] $Tree)
    $item = $Tree.SelectedItem
    if ($null -eq $item -or [string]::IsNullOrWhiteSpace($item.Tag)) { return $null }
    return [string] $item.Tag
}

function Add-NcsLimitPickerValue {
    param([Parameter(Mandatory)] $TextBox, [Parameter(Mandatory)] [string] $Value)
    $current = $TextBox.Text.Trim()
    if ([string]::IsNullOrWhiteSpace($current)) { $TextBox.Text = $Value }
    else { $TextBox.Text = "$current,$Value" }
}

function Test-NcsLimitPickerContains {
    param([Parameter(Mandatory)] $TextBox, [Parameter(Mandatory)] [string] $Tag)
    $current = $TextBox.Text.Trim()
    $parts = @($current -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
    return ($parts -contains $Tag -or $parts -contains "!$Tag" -or $parts -contains ":&$Tag" -or $parts -contains "$Tag*")
}

function Remove-NcsLimitPickerValue {
    param([Parameter(Mandatory)] $TextBox, [Parameter(Mandatory)] [string] $Tag)
    $current = $TextBox.Text.Trim()
    $parts = @($current -split ',' | ForEach-Object { $_.Trim() } | Where-Object {
        $_ -ne '' -and $_ -ne $Tag -and $_ -ne "!$Tag" -and $_ -ne ":&$Tag" -and $_ -ne "$Tag*"
    })
    $TextBox.Text = $parts -join ','
}

function New-NcsLimitPickerMenuItem {
    param([Parameter(Mandatory)] [string] $Header, [Parameter(Mandatory)] [string] $Op)
    $item = [System.Windows.Controls.MenuItem]::new()
    $item.Header = $Header
    $item.Tag = $Op
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
    $item.Add_Click({
        param($sender, $e)
        Invoke-NcsLimitPickerMenuClick -MenuItem $sender
    })
    return $item
}

function Invoke-NcsLimitPickerMenuClick {
    param([Parameter(Mandatory)] [System.Windows.Controls.MenuItem] $MenuItem)
    $parent = $MenuItem.Parent
    while ($null -ne $parent -and $parent -isnot [System.Windows.Controls.ContextMenu]) {
        $parent = $parent.Parent
    }
    if ($null -eq $parent) { return }
    $tree = $parent.PlacementTarget
    $ctx = Get-NcsLimitPickerContext -Tree $tree
    if ($null -eq $ctx) { return }
    $op = [string] $MenuItem.Tag
    if ($op -eq "Clear") { $ctx.TextBox.Text = ""; return }
    $tag = Get-NcsLimitPickerSelectedTag -Tree $ctx.Tree
    if ($op -eq "Remove") {
        if ($tag) { Remove-NcsLimitPickerValue -TextBox $ctx.TextBox -Tag $tag }
        return
    }
    if (-not $tag) { return }
    switch ($op) {
        "Add"       { Add-NcsLimitPickerValue -TextBox $ctx.TextBox -Value $tag }
        "Exclude"   { Add-NcsLimitPickerValue -TextBox $ctx.TextBox -Value "!$tag" }
        "Intersect" { Add-NcsLimitPickerValue -TextBox $ctx.TextBox -Value ":&$tag" }
        "Wildcard"  { Add-NcsLimitPickerValue -TextBox $ctx.TextBox -Value "$tag*" }
    }
}

function New-NcsLimitPickerSeparator {
    $sep = [System.Windows.Controls.Separator]::new()
    $sep.Template = [System.Windows.Markup.XamlReader]::Parse(
        '<ControlTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" TargetType="Separator">' +
        '<Border Height="1" Background="#2c3038" Margin="4,2,4,2" />' +
        '</ControlTemplate>'
    )
    return $sep
}

function Register-NcsLimitPicker {
    <#
    .SYNOPSIS Wire up a Target Host/Group (--limit) picker: inventory TreeView composes
              values into a TextBox via a right-click context menu and double-click toggle.
    .DESCRIPTION Used for both the Actions pane and the Schedule edit form. The caller
                 is responsible for populating the tree via Build-NcsTreeView; this
                 function only installs the interaction layer. Picker context is stored
                 in $script:NcsLimitPickers keyed by tree identity; event handlers retrieve
                 it via $sender/ContextMenu.PlacementTarget to avoid closure scope issues
                 under Set-StrictMode.
    #>
    param(
        [Parameter(Mandatory)] [System.Windows.Controls.TextBox] $TextBox,
        [Parameter(Mandatory)] [System.Windows.Controls.TreeView] $Tree,
        [Parameter(Mandatory)] [System.Windows.Controls.ScrollViewer] $ScrollViewer,
        [scriptblock] $OnChanged,
        # Skip Exclude/Intersect/Wildcard items — appropriate for flat pickers
        # (tags) where Ansible doesn't support those composition operators.
        [switch] $Simple
    )

    $ctx = [pscustomobject]@{
        TextBox      = $TextBox
        Tree         = $Tree
        ScrollViewer = $ScrollViewer
        OnChanged    = $OnChanged
    }
    $script:NcsLimitPickers[[System.Runtime.CompilerServices.RuntimeHelpers]::GetHashCode($Tree)]    = $ctx
    $script:NcsLimitPickers[[System.Runtime.CompilerServices.RuntimeHelpers]::GetHashCode($TextBox)] = $ctx

    $menu = [System.Windows.Controls.ContextMenu]::new()
    $menu.Template = [System.Windows.Markup.XamlReader]::Parse(
        '<ControlTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" TargetType="ContextMenu">' +
        '<Border Background="#1e2228" BorderBrush="#2c3038" BorderThickness="1" Padding="0" MinWidth="140">' +
        '<StackPanel IsItemsHost="True" KeyboardNavigation.DirectionalNavigation="Cycle" />' +
        '</Border>' +
        '</ControlTemplate>'
    )

    $menu.Items.Add((New-NcsLimitPickerMenuItem "Add"    "Add"))    | Out-Null
    $menu.Items.Add((New-NcsLimitPickerMenuItem "Remove" "Remove")) | Out-Null
    if (-not $Simple) {
        $menu.Items.Add((New-NcsLimitPickerSeparator)) | Out-Null
        $menu.Items.Add((New-NcsLimitPickerMenuItem "Exclude (!)"    "Exclude"))   | Out-Null
        $menu.Items.Add((New-NcsLimitPickerMenuItem "Intersect (:&)" "Intersect")) | Out-Null
        $menu.Items.Add((New-NcsLimitPickerMenuItem "Wildcard (*)"   "Wildcard"))  | Out-Null
    }
    $menu.Items.Add((New-NcsLimitPickerSeparator)) | Out-Null
    $menu.Items.Add((New-NcsLimitPickerMenuItem "Clear all" "Clear")) | Out-Null

    $menu.Add_Opened({
        param($sender, $e)
        $tree = $sender.PlacementTarget
        $ctx = Get-NcsLimitPickerContext -Tree $tree
        if ($null -eq $ctx) { return }
        $pos = [System.Windows.Input.Mouse]::GetPosition($tree)
        $hit = [System.Windows.Media.VisualTreeHelper]::HitTest($tree, $pos)
        if ($null -ne $hit -and $null -ne $hit.VisualHit) {
            $element = $hit.VisualHit
            while ($null -ne $element -and $element -isnot [System.Windows.Controls.TreeViewItem]) {
                $element = [System.Windows.Media.VisualTreeHelper]::GetParent($element)
            }
            if ($null -ne $element) { $element.IsSelected = $true }
        }
        $tag = Get-NcsLimitPickerSelectedTag -Tree $tree
        $removeEnabled = $false
        if ($tag) { $removeEnabled = Test-NcsLimitPickerContains -TextBox $ctx.TextBox -Tag $tag }
        foreach ($mi in $sender.Items) {
            if ($mi -is [System.Windows.Controls.MenuItem] -and $mi.Header -eq "Remove") {
                $mi.IsEnabled = $removeEnabled
            }
        }
    })

    $Tree.ContextMenu = $menu

    $Tree.Add_MouseDoubleClick({
        param($sender, $e)
        $ctx = Get-NcsLimitPickerContext -Tree $sender
        if ($null -eq $ctx) { return }
        $selected = $sender.SelectedItem
        if ($null -eq $selected -or $selected.Items.Count -gt 0) { return }
        $tag = Get-NcsLimitPickerSelectedTag -Tree $sender
        if (-not $tag) { return }
        if (Test-NcsLimitPickerContains -TextBox $ctx.TextBox -Tag $tag) {
            Remove-NcsLimitPickerValue -TextBox $ctx.TextBox -Tag $tag
        } else {
            Add-NcsLimitPickerValue -TextBox $ctx.TextBox -Value $tag
        }
        $e.Handled = $true
    })

    $Tree.Add_PreviewMouseWheel({
        param($sender, $e)
        $ctx = Get-NcsLimitPickerContext -Tree $sender
        if ($null -eq $ctx) { return }
        $ctx.ScrollViewer.ScrollToVerticalOffset($ctx.ScrollViewer.VerticalOffset - $e.Delta / 3)
        $e.Handled = $true
    })

    if ($null -ne $OnChanged) {
        $TextBox.Add_TextChanged({
            param($sender, $e)
            $ctx = Get-NcsLimitPickerContext -Tree $sender
            if ($null -ne $ctx -and $null -ne $ctx.OnChanged) { & $ctx.OnChanged }
        })
    }
}

function Show-NcsPasswordPrompt {
    param(
        [Parameter(Mandatory)] [System.Windows.Window] $Owner,
        [Parameter(Mandatory)] [string] $Title,
        [Parameter(Mandatory)] [string] $Prompt,
        [string] $OkLabel = "OK"
    )

    $inputBox = [System.Windows.Window]::new()
    $inputBox.Title = ""
    $inputBox.Width = 350
    $inputBox.SizeToContent = "Height"
    $inputBox.WindowStartupLocation = "CenterOwner"
    $inputBox.Owner = $Owner
    $inputBox.WindowStyle = "None"
    $inputBox.ResizeMode = "NoResize"
    $inputBox.Background = Get-NcsBrush -Color "#181b1f"
    $inputBox.BorderBrush = Get-NcsBrush -Color "#2c3038"
    $inputBox.BorderThickness = [System.Windows.Thickness]::new(1)

    $sp = [System.Windows.Controls.StackPanel]::new()
    $sp.Margin = [System.Windows.Thickness]::new(16)

    $titleBlock = [System.Windows.Controls.TextBlock]::new()
    $titleBlock.Text = $Title
    $titleBlock.Foreground = Get-NcsBrush -Color "#d8dce2"
    $titleBlock.FontSize = 14
    $titleBlock.FontWeight = "Bold"
    $titleBlock.Margin = [System.Windows.Thickness]::new(0,0,0,8)
    $sp.Children.Add($titleBlock) | Out-Null

    $label = [System.Windows.Controls.TextBlock]::new()
    $label.Text = $Prompt
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
    $okBtn.Content = $OkLabel
    $okBtn.Background = Get-NcsBrush -Color "#1e2228"
    $okBtn.Foreground = Get-NcsBrush -Color "#d8dce2"
    $okBtn.BorderBrush = Get-NcsBrush -Color "#2c3038"
    $okBtn.Padding = [System.Windows.Thickness]::new(12,5,12,5)
    $okBtn.Margin = [System.Windows.Thickness]::new(6,0,0,0)
    $okBtn.IsDefault = $true
    $okBtn.Add_Click({ $inputBox.DialogResult = $true }.GetNewClosure())

    $cancelBtn = [System.Windows.Controls.Button]::new()
    $cancelBtn.Content = "Cancel"
    $cancelBtn.Background = Get-NcsBrush -Color "#1e2228"
    $cancelBtn.Foreground = Get-NcsBrush -Color "#8e939c"
    $cancelBtn.BorderBrush = Get-NcsBrush -Color "#2c3038"
    $cancelBtn.Padding = [System.Windows.Thickness]::new(12,5,12,5)
    $cancelBtn.Add_Click({ $inputBox.DialogResult = $false }.GetNewClosure())

    $btnPanel.Children.Add($cancelBtn) | Out-Null
    $btnPanel.Children.Add($okBtn) | Out-Null
    $sp.Children.Add($btnPanel) | Out-Null
    $inputBox.Content = $sp
    $pwBox.Focus() | Out-Null

    if ($inputBox.ShowDialog() -eq $true) {
        return $pwBox.Password
    }
    return $null
}

function Import-NcsWpfAssemblies {
    param(
        [string] $ProjectRoot
    )

    Add-Type -AssemblyName PresentationCore
    Add-Type -AssemblyName PresentationFramework
    Add-Type -AssemblyName WindowsBase

    $script:NcsWebView2Available = $false
    $script:NcsWebView2Status = "WebView2 app dependencies are not installed."

    if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
        return
    }

    $webViewRoot = Join-Path -Path $ProjectRoot -ChildPath "App/lib/WebView2"
    $coreAssemblyPath = Join-Path -Path $webViewRoot -ChildPath "Microsoft.Web.WebView2.Core.dll"
    $wpfAssemblyPath = Join-Path -Path $webViewRoot -ChildPath "Microsoft.Web.WebView2.Wpf.dll"
    $loaderDir = Join-Path -Path $webViewRoot -ChildPath $(if ([Environment]::Is64BitProcess) { "x64" } else { "x86" })
    $loaderPath = Join-Path -Path $loaderDir -ChildPath "WebView2Loader.dll"

    if (-not (Test-Path -LiteralPath $coreAssemblyPath) -or -not (Test-Path -LiteralPath $wpfAssemblyPath) -or -not (Test-Path -LiteralPath $loaderPath)) {
        $script:NcsWebView2Status = "WebView2 app dependencies are missing from App/lib/WebView2."
        return
    }

    try {
        if ($env:PATH -notlike "*$loaderDir*") {
            $env:PATH = "{0}{1}{2}" -f $loaderDir, [IO.Path]::PathSeparator, $env:PATH
        }
        # Pre-load the native DLL so the managed assemblies can find it via P/Invoke
        Add-Type -TypeDefinition 'using System.Runtime.InteropServices; public class NcsNativeLoader { [DllImport("kernel32")] public static extern System.IntPtr LoadLibrary(string path); }' -ErrorAction SilentlyContinue
        [void][NcsNativeLoader]::LoadLibrary($loaderPath)
        Add-Type -Path $coreAssemblyPath
        Add-Type -Path $wpfAssemblyPath
        $script:NcsWebView2Available = $true
        $script:NcsWebView2Status = ""
    } catch {
        $script:NcsWebView2Status = "WebView2 app dependencies failed to load: $($_.Exception.Message)"
    }
}

function Test-NcsSmbAccess {
    param(
        [Parameter(Mandatory)]
        [NcsConsoleSettings] $Settings
    )

    $uncRoot = "\\$($Settings.SshHost)\$($Settings.SmbShareName)"
    try {
        $tcp = [System.Net.Sockets.TcpClient]::new()
        try {
            $task = $tcp.ConnectAsync($Settings.SshHost, 445)
            $connected = $task.Wait(2000)
            if (-not $connected -or -not $tcp.Connected) {
                return [pscustomobject]@{ Accessible = $false; UncRoot = $uncRoot; Error = "SMB port 445 unreachable" }
            }
        } finally {
            $tcp.Dispose()
        }

        # Authenticate with explicit SMB credentials via a transient PSDrive
        if (-not [string]::IsNullOrWhiteSpace($Settings.SmbUser)) {
            $secPass = if (-not [string]::IsNullOrWhiteSpace($Settings.SmbPassword)) {
                ConvertTo-SecureString $Settings.SmbPassword -AsPlainText -Force
            } else {
                [System.Security.SecureString]::new()
            }
            $cred = [PSCredential]::new($Settings.SmbUser, $secPass)
            try {
                New-PSDrive -Name "NcsSmbProbe" -PSProvider FileSystem -Root $uncRoot -Credential $cred -ErrorAction Stop | Out-Null
                Remove-PSDrive -Name "NcsSmbProbe" -Force -ErrorAction SilentlyContinue
            } catch {
                return [pscustomobject]@{ Accessible = $false; UncRoot = $uncRoot; Error = "SMB authentication failed: $($_.Exception.Message)" }
            }
        }

        $accessible = Test-Path -LiteralPath $uncRoot -ErrorAction Stop
        return [pscustomobject]@{ Accessible = $accessible; UncRoot = $uncRoot; Error = "" }
    } catch {
        return [pscustomobject]@{ Accessible = $false; UncRoot = $uncRoot; Error = $_.Exception.Message }
    }
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
    $stagingRoot = "{0}.staging" -f $LocalRoot
    if (Test-Path -LiteralPath $stagingRoot) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }
    [System.IO.Directory]::CreateDirectory($stagingRoot) | Out-Null

    $arguments = [System.Collections.Generic.List[string]]::new()
    $arguments.Add("-r")
    $arguments.Add("-P")
    $arguments.Add([string] $Settings.SshPort)
    Add-NcsSshCommonOptions -Arguments $arguments -Settings $Settings
    Add-NcsSshAuthOptions -Arguments $arguments -Settings $Settings

    $environment = Get-NcsSshEnvironment -Settings $Settings

    $remoteSpec = "{0}:{1}" -f (Get-NcsSshTarget -Settings $Settings), $Settings.RemoteReportsPath
    $arguments.Add($remoteSpec)
    $arguments.Add($cacheParent)

    $mirror = Invoke-NcsToolCommand -FilePath "scp.exe" -Arguments $arguments -Environment $environment -TimeoutMs 180000
    if ($mirror.ExitCode -eq 0) {
        $incomingRoot = Join-Path -Path $cacheParent -ChildPath ([IO.Path]::GetFileName($Settings.RemoteReportsPath))
        if (-not (Test-Path -LiteralPath $incomingRoot)) {
            $incomingRoot = $stagingRoot
        } elseif ($incomingRoot -ne $stagingRoot) {
            if (Test-Path -LiteralPath $stagingRoot) {
                Remove-Item -LiteralPath $stagingRoot -Recurse -Force
            }
            Move-Item -LiteralPath $incomingRoot -Destination $stagingRoot
        }
        if (Test-Path -LiteralPath $LocalRoot) {
            Remove-Item -LiteralPath $LocalRoot -Recurse -Force
        }
        Move-Item -LiteralPath $stagingRoot -Destination $LocalRoot
    } elseif (Test-Path -LiteralPath $stagingRoot) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }

    return $mirror
}

function Get-NcsXamlControlMap {
    param(
        [Parameter(Mandatory)]
        [System.Windows.Window] $Window
    )

    $map = @{}
    foreach ($name in @(
        "OuterChromeBorder",
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
        "SmbShareNameTextBox",
        "SmbUserTextBox",
        "ReportDeliveryModeComboBox",
        "AutoRefreshIntervalTextBox",
        "SaveSettingsButton",
        "PreflightButton",
        "PreflightButtonText",
        "RefreshPlaybooksButton",
        "PlaybooksCloseButton",
        "PlaybookPlaceholder",
        "PlaybookSplitPane",
        "ActionTreeView",
        "ActionPropertiesPanel",
        "ActionSelectionTitle",
        "ActionLimitTextBox",
        "ActionLimitTree",
        "ActionLimitTreeBorder",
        "ActionLimitTreeScroll",
        "ActionLimitEmptyText",
        "ActionTagsTextBox",
        "ActionTagsTree",
        "ActionTagsTreeBorder",
        "ActionTagsTreeScroll",
        "ActionTagsEmptyText",
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
        "ReportsColumn",
        "ReportsToggleButton",
        "ReportsPane",
        "ReportsSplitter",
        "ReportHost",
        "ReportPlaceholderPanel",
        "ReportPlaceholder",
        "ReportBackButton",
        "ReportHomeButton",
        "ReportRefreshButton",
        "ReportsCloseButton",
        "ReportsMaximizeButton",
        "SchedulesColumn",
        "SchedulesToggleButton",
        "SchedulesPane",
        "SchedulesSplitter",
        "SchedulesCloseButton",
        "ScheduleRefreshButton",
        "ScheduleAddButton",
        "SchedulePlaceholder",
        "ScheduleListView",
        "ScheduleEditPanel",
        "ScheduleEditTitle",
        "ScheduleNameTextBox",
        "ScheduleCalendarTextBox",
        "ScheduleDescriptionTextBox",
        "SchedulePlaybookComboBox",
        "ScheduleLimitTextBox",
        "ScheduleLimitTree",
        "ScheduleLimitTreeBorder",
        "ScheduleLimitTreeScroll",
        "ScheduleLimitEmptyText",
        "ScheduleTagsTextBox",
        "ScheduleTagsTree",
        "ScheduleTagsTreeBorder",
        "ScheduleTagsTreeScroll",
        "ScheduleTagsEmptyText",
        "ScheduleTimeoutTextBox",
        "ScheduleExtraArgsTextBox",
        "ScheduleEnabledCheckBox",
        "ScheduleCheckModeCheckBox",
        "ScheduleNotifyCheckBox",
        "ScheduleDeleteButton",
        "ScheduleCancelButton",
        "ScheduleSaveButton",
        "StatusTextBlock",
        "ExitCodePanel",
        "ExitCodeTextBlock",
        "DurationPanel",
        "DurationTextBlock",
        "RunStateBorder",
        "SshKeyPathPanel",
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

function New-NcsLeafTreeItem {
    param($Item, [string] $TagProperty, [string] $LeafIcon)
    $leafItem = [System.Windows.Controls.TreeViewItem]::new()
    $leafItem.Tag = $Item[$TagProperty]
    $leafItem.ToolTip = $Item.Label
    $displayText = if ($Item[$TagProperty]) { [System.IO.Path]::GetFileName($Item[$TagProperty]) } else { $Item.Label }
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
        $tb.Text = $displayText
        $tb.VerticalAlignment = "Center"
        $sp.Children.Add($tb) | Out-Null
        $leafItem.Header = $sp
    } else {
        $leafItem.Header = $displayText
    }
    return $leafItem
}

function New-NcsGroupTreeItem {
    param($Group, [string] $TagProperty, [bool] $Expanded, [string] $LeafIcon)
    $groupItem = [System.Windows.Controls.TreeViewItem]::new()
    $groupItem.Header = $Group.Group
    $groupItem.Tag = $Group.Group
    $groupItem.IsExpanded = $Expanded
    # Child groups first (subdirectories)
    if ($Group.ContainsKey('Children') -and $null -ne $Group['Children']) {
        foreach ($child in @($Group['Children'])) {
            $childItem = New-NcsGroupTreeItem -Group $child -TagProperty $TagProperty -Expanded $Expanded -LeafIcon $LeafIcon
            $groupItem.Items.Add($childItem) | Out-Null
        }
    }
    # Leaf items (playbooks in this directory)
    foreach ($item in @($Group.Items)) {
        $leafItem = New-NcsLeafTreeItem -Item $item -TagProperty $TagProperty -LeafIcon $LeafIcon
        $groupItem.Items.Add($leafItem) | Out-Null
    }
    return $groupItem
}

function Get-NcsTreeViewItemStyle {
    # Custom TreeViewItem style: only highlight on direct hover (not when children are hovered).
    # Uses a minimal ControlTemplate with IsMouseDirectlyOver trigger instead of IsMouseOver.
    if ($null -eq $script:_NcsTreeViewItemStyle) {
        $xaml = @'
<Style xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
       xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
       TargetType="TreeViewItem">
  <Setter Property="Foreground" Value="#d8dce2" />
  <Setter Property="Background" Value="Transparent" />
  <Setter Property="Padding" Value="2,1,4,1" />
  <Setter Property="Template">
    <Setter.Value>
      <ControlTemplate TargetType="TreeViewItem">
        <StackPanel>
          <Border x:Name="Bd" Background="{TemplateBinding Background}" Padding="{TemplateBinding Padding}">
            <DockPanel>
              <ToggleButton x:Name="Expander" DockPanel.Dock="Left" ClickMode="Press"
                            IsChecked="{Binding IsExpanded, RelativeSource={RelativeSource TemplatedParent}}"
                            Width="14" Margin="0,0,2,0" Focusable="False">
                <ToggleButton.Template>
                  <ControlTemplate TargetType="ToggleButton">
                    <Border Background="Transparent" Width="14" Height="14">
                      <Path x:Name="Arrow" HorizontalAlignment="Center" VerticalAlignment="Center"
                            Data="M0,0 L4,4 L0,8" Stroke="#6e737c" StrokeThickness="1.2"
                            Width="8" Height="8" Stretch="Uniform" />
                    </Border>
                    <ControlTemplate.Triggers>
                      <Trigger Property="IsChecked" Value="True">
                        <Setter TargetName="Arrow" Property="Data" Value="M0,0 L4,4 L8,0" />
                      </Trigger>
                    </ControlTemplate.Triggers>
                  </ControlTemplate>
                </ToggleButton.Template>
              </ToggleButton>
              <ContentPresenter x:Name="PART_Header" ContentSource="Header" VerticalAlignment="Center" />
            </DockPanel>
          </Border>
          <ItemsPresenter x:Name="ItemsHost" Margin="14,0,0,0" Visibility="Collapsed" />
        </StackPanel>
        <ControlTemplate.Triggers>
          <Trigger Property="IsExpanded" Value="True">
            <Setter TargetName="ItemsHost" Property="Visibility" Value="Visible" />
          </Trigger>
          <Trigger Property="HasItems" Value="False">
            <Setter TargetName="Expander" Property="Visibility" Value="Hidden" />
          </Trigger>
          <Trigger SourceName="Bd" Property="IsMouseDirectlyOver" Value="True">
            <Setter TargetName="Bd" Property="Background" Value="#1a1e26" />
          </Trigger>
          <Trigger Property="IsSelected" Value="True">
            <Setter TargetName="Bd" Property="Background" Value="#242932" />
          </Trigger>
        </ControlTemplate.Triggers>
      </ControlTemplate>
    </Setter.Value>
  </Setter>
</Style>
'@
        $script:_NcsTreeViewItemStyle = [System.Windows.Markup.XamlReader]::Parse($xaml)
    }
    return $script:_NcsTreeViewItemStyle
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
    $tree.ItemContainerStyle = Get-NcsTreeViewItemStyle
    foreach ($group in $Groups) {
        $groupItem = New-NcsGroupTreeItem -Group $group -TagProperty $TagProperty -Expanded $Expanded -LeafIcon $LeafIcon
        $tree.Items.Add($groupItem) | Out-Null
    }
}

function Find-NcsTreeViewItemByTag {
    param($Parent, [string] $Tag)
    foreach ($child in @($Parent.Items)) {
        if ($child.Tag -eq $Tag) { return $child }
        $found = Find-NcsTreeViewItemByTag -Parent $child -Tag $Tag
        if ($null -ne $found) { return $found }
    }
    return $null
}

function Find-NcsFirstLeafItem {
    param($Parent)
    foreach ($child in @($Parent.Items)) {
        # A leaf has a Tag that looks like a playbook path (contains '.')
        if ($null -ne $child.Tag -and $child.Tag -match '\.ya?ml$') { return $child }
        $found = Find-NcsFirstLeafItem -Parent $child
        if ($null -ne $found) { return $found }
    }
    return $null
}

function Select-NcsTreeViewItem {
    param(
        [Parameter(Mandatory)]
        [System.Windows.Controls.TreeView] $TreeView,
        [string] $Tag,
        [switch] $FallbackToFirst
    )

    if (-not [string]::IsNullOrWhiteSpace($Tag)) {
        $found = Find-NcsTreeViewItemByTag -Parent $TreeView -Tag $Tag
        if ($null -ne $found) {
            $found.IsSelected = $true
            return
        }
    }

    if ($FallbackToFirst -and $TreeView.Items.Count -gt 0) {
        $first = Find-NcsFirstLeafItem -Parent $TreeView
        if ($null -ne $first) {
            $first.IsSelected = $true
        }
    }
}

function Get-NcsActionItemMap {
    param($Groups)

    $map = @{}
    foreach ($group in @($Groups)) {
        foreach ($item in @($group.Items)) {
            if ($item.ContainsKey('playbook') -and -not [string]::IsNullOrWhiteSpace($item.playbook)) {
                $map[[string]$item.playbook] = $item
            }
        }
        if ($group.ContainsKey('Children') -and $null -ne $group['Children']) {
            foreach ($kv in (Get-NcsActionItemMap -Groups $group['Children']).GetEnumerator()) {
                $map[$kv.Key] = $kv.Value
            }
        }
    }
    return $map
}

function Get-NcsSchedulePlaybookChoices {
    param(
        $ScheduleEntries,
        [string[]] $BaseChoices,
        [string] $Include
    )

    $playbooks = [System.Collections.Generic.SortedSet[string]]::new()
    foreach ($pb in @($BaseChoices)) {
        if (-not [string]::IsNullOrWhiteSpace($pb)) { [void]$playbooks.Add([string]$pb) }
    }
    foreach ($entry in @($ScheduleEntries)) {
        if ($null -ne $entry -and -not [string]::IsNullOrWhiteSpace($entry.Playbook)) {
            [void]$playbooks.Add([string]$entry.Playbook)
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($Include)) { [void]$playbooks.Add($Include) }
    return [string[]]$playbooks
}

function Initialize-NcsWorkerPool {
    # Only load what Get-NcsRemotePlaybookTags transitively needs.
    param([Parameter(Mandatory)] [string] $ModuleRoot)

    $iss = [System.Management.Automation.Runspaces.InitialSessionState]::CreateDefault()
    foreach ($module in @("NcsConsole.Types.ps1", "NcsConsole.Execution.ps1", "NcsConsole.Preflight.ps1")) {
        $path = Join-Path -Path $ModuleRoot -ChildPath $module
        [void] $iss.StartupScripts.Add($path)
    }
    # BeginOpen returns immediately; BeginInvoke queues until the pool finishes
    # opening, so startup isn't blocked on parsing the worker's StartupScripts.
    $pool = [runspacefactory]::CreateRunspacePool(1, 2, $iss, $Host)
    [void] $pool.BeginOpen($null, $null)
    return $pool
}

function Stop-NcsTagFetches {
    foreach ($kv in @($script:TagFetchInFlight.GetEnumerator())) {
        try { $kv.Value.Timer.Stop() } catch { $null = $_ }
        try { $kv.Value.PS.Stop() } catch { $null = $_ }
        try { $kv.Value.PS.Dispose() } catch { $null = $_ }
    }
    $script:TagFetchInFlight = @{}
}

function ConvertTo-NcsSettingsHashtable {
    # Cross-runspace PS class identity differs, so flatten to a plain hashtable
    # and rehydrate on the worker side via [NcsConsoleSettings]::new().
    param([Parameter(Mandatory)] $Settings)
    $h = @{}
    foreach ($prop in $Settings.PSObject.Properties) { $h[$prop.Name] = $prop.Value }
    return $h
}

function Add-NcsOptionControls {
    param(
        [Parameter(Mandatory)]
        [System.Windows.Controls.Panel] $Panel,
        $Options
    )

    if ($null -eq $Options -or @($Options).Length -eq 0) { return }

    foreach ($opt in @($Options)) {
        $optType = if ($opt.ContainsKey('type')) { $opt['type'] } else { 'text' }
        $tip = if ($opt.ContainsKey('tooltip')) { $opt['tooltip'] } else { $null }

        if ($optType -ne 'bool') {
            $label = [System.Windows.Controls.TextBlock]::new()
            $label.Text = $opt['label']
            $label.Foreground = Get-NcsBrush -Color "#8e939c"
            $label.FontSize = 11
            if ($tip) { $label.ToolTip = $tip }
            $Panel.Children.Add($label) | Out-Null
        }

        switch ($optType) {
            'select' {
                $comboBox = [System.Windows.Controls.ComboBox]::new()
                $comboBox.Tag = $opt['name']
                if ($tip) { $comboBox.ToolTip = $tip }
                if ($opt.ContainsKey('choices')) {
                    $comboBox.ItemsSource = @($opt['choices'])
                }
                if ($opt.ContainsKey('default')) {
                    $comboBox.SelectedItem = $opt['default']
                }
                if ($null -eq $comboBox.SelectedItem -and $comboBox.Items.Count -gt 0) {
                    $comboBox.SelectedIndex = 0
                }
                $Panel.Children.Add($comboBox) | Out-Null
            }
            'bool' {
                $checkBox = [System.Windows.Controls.CheckBox]::new()
                $checkBox.Tag = $opt['name']
                $checkBox.Content = $opt['label']
                $checkBox.Foreground = Get-NcsBrush -Color "#8e939c"
                $checkBox.FontSize = 11
                $checkBox.Margin = [System.Windows.Thickness]::new(0, 4, 0, 0)
                if ($tip) { $checkBox.ToolTip = $tip }
                if ($opt.ContainsKey('default')) {
                    $dv = $opt['default']
                    $checkBox.IsChecked = ($dv -eq $true -or $dv -eq 'true' -or $dv -eq 'yes')
                }
                $Panel.Children.Add($checkBox) | Out-Null
            }
            default {
                $isPassword = $opt['name'] -match 'password|secret|passphrase'
                if ($isPassword) {
                    $pwBox = [System.Windows.Controls.PasswordBox]::new()
                    $pwBox.Tag = $opt['name']
                    if ($tip) { $pwBox.ToolTip = $tip }
                    if ($opt.ContainsKey('default')) { $pwBox.Password = $opt['default'] }
                    $Panel.Children.Add($pwBox) | Out-Null
                } else {
                    $textBox = [System.Windows.Controls.TextBox]::new()
                    $textBox.Tag = $opt['name']
                    if ($tip) { $textBox.ToolTip = $tip }
                    if ($opt.ContainsKey('default')) { $textBox.Text = $opt['default'] }
                    $Panel.Children.Add($textBox) | Out-Null
                }
            }
        }
    }
}

function Update-NcsActionOptions {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls,
        $ActionItem
    )

    $Controls.ActionOptionsPanel.Children.Clear()
    $Controls.ActionOptionsPanel.Visibility = "Collapsed"

    if ($null -eq $ActionItem) { return }

    $hasProfiles = $ActionItem.ContainsKey('profiles') -and @($ActionItem['profiles']).Length -gt 0
    $hasOptions = $ActionItem.ContainsKey('options') -and @($ActionItem['options']).Length -gt 0

    if (-not $hasProfiles -and -not $hasOptions) { return }

    $Controls.ActionOptionsPanel.Visibility = "Visible"

    if ($hasProfiles) {
        $profiles = @($ActionItem['profiles'])

        $profileLabel = [System.Windows.Controls.TextBlock]::new()
        $profileLabel.Text = "Operation"
        $profileLabel.Foreground = Get-NcsBrush -Color "#8e939c"
        $profileLabel.FontSize = 11
        $Controls.ActionOptionsPanel.Children.Add($profileLabel) | Out-Null

        $profileCombo = [System.Windows.Controls.ComboBox]::new()
        $profileCombo.Tag = "_ncs_profile_selector"
        $profileCombo.ItemsSource = @($profiles | ForEach-Object { $_.label })
        $profileCombo.SelectedIndex = 0

        $profileOptionsPanel = [System.Windows.Controls.StackPanel]::new()
        $profileOptionsPanel.Tag = "_ncs_profile_options"

        $updateProfileOptions = {
            param($Panel, $Profiles, $Index)
            $Panel.Children.Clear()
            if ($Index -lt 0 -or $Index -ge $Profiles.Length) { return }
            $p = $Profiles[$Index]
            if ($p.ContainsKey('operation')) {
                $opField = [System.Windows.Controls.TextBox]::new()
                $opField.Tag = "ncs_operation"
                $opField.Text = $p['operation']
                $opField.Visibility = "Collapsed"
                $Panel.Children.Add($opField) | Out-Null
            }
            if ($p.ContainsKey('options')) {
                Add-NcsOptionControls -Panel $Panel -Options $p['options']
            }
        }

        & $updateProfileOptions $profileOptionsPanel $profiles 0

        $profileCombo.Add_SelectionChanged({
            & $updateProfileOptions $profileOptionsPanel $profiles $profileCombo.SelectedIndex
        }.GetNewClosure())

        $Controls.ActionOptionsPanel.Children.Add($profileCombo) | Out-Null
        $Controls.ActionOptionsPanel.Children.Add($profileOptionsPanel) | Out-Null
    } else {
        Add-NcsOptionControls -Panel $Controls.ActionOptionsPanel -Options $ActionItem['options']
    }
}

function Get-NcsControlValues {
    param([System.Windows.Controls.Panel] $Panel)
    $values = @{}
    foreach ($child in @($Panel.Children)) {
        if ($child -is [System.Windows.Controls.Panel]) {
            foreach ($kv in (Get-NcsControlValues -Panel $child).GetEnumerator()) {
                $values[$kv.Key] = $kv.Value
            }
            continue
        }
        if ([string]::IsNullOrWhiteSpace($child.Tag) -or $child.Tag.StartsWith('_ncs_')) { continue }
        if ($child -is [System.Windows.Controls.TextBox]) {
            $val = $child.Text.Trim()
            if (-not [string]::IsNullOrWhiteSpace($val)) {
                $values[$child.Tag] = $val
            }
        } elseif ($child -is [System.Windows.Controls.ComboBox]) {
            $val = [string] $child.SelectedItem
            if (-not [string]::IsNullOrWhiteSpace($val)) {
                $values[$child.Tag] = $val
            }
        } elseif ($child -is [System.Windows.Controls.PasswordBox]) {
            $val = $child.Password
            if (-not [string]::IsNullOrWhiteSpace($val)) {
                $values[$child.Tag] = $val
            }
        } elseif ($child -is [System.Windows.Controls.CheckBox]) {
            $values[$child.Tag] = if ($child.IsChecked) { "true" } else { "false" }
        }
    }
    return $values
}

function Get-NcsActionOptionValues {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls
    )
    return Get-NcsControlValues -Panel $Controls.ActionOptionsPanel
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

    $Controls.SshKeyPathPanel.Visibility = if ($AuthMode -eq [NcsSshAuthMode]::KeyFile) { "Visible" } else { "Collapsed" }
    $Controls.SshPasswordPanel.Visibility = if ($AuthMode -eq [NcsSshAuthMode]::Password) { "Visible" } else { "Collapsed" }
}

function Set-NcsRunStateBadge {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls,
        [Parameter(Mandatory)]
        [string] $State
    )

    $Controls.RunStateText.Text = $State
    $styles = @{
        Succeeded = @{ bg = "#6e9fff"; fg = "#ffffff"; meta = "#d8e4ff" }
        Failed    = @{ bg = "#f2495c"; fg = "#ffffff"; meta = "#8e939c" }
        Canceled  = @{ bg = "#ff9830"; fg = "#1e2228"; meta = "#3d3020" }
        Blocked   = @{ bg = "#f2495c"; fg = "#ffffff"; meta = "#8e939c" }
    }
    $s = if ($styles.ContainsKey($State)) { $styles[$State] } else { @{ bg = "#1e2228"; fg = "#ffffff"; meta = "#8e939c" } }
    $Controls.RunStateBorder.Background = Get-NcsBrush -Color $s.bg
    $Controls.RunStateText.Foreground = Get-NcsBrush -Color $s.fg
    $Controls.RunMetaText.Foreground = Get-NcsBrush -Color $s.meta
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
        $Controls.OuterChromeBorder.BorderThickness = [System.Windows.Thickness]::new(0)
    }
    else {
        $path.Data = [System.Windows.Media.Geometry]::Parse("M0 0 L10 0 L10 10 L0 10 Z")
        $Controls.OuterChromeBorder.BorderThickness = [System.Windows.Thickness]::new(1)
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
    $Controls.SchedulesToggleButton.Tag = if ($Controls.SchedulesPane.Visibility -eq "Visible") { "Active" } else { "Inactive" }
}

function Set-NcsPreflightState {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls,
        [Parameter(Mandatory)]
        [string] $State
    )

    if ($State -eq "Connected") {
        $Controls.PreflightButtonText.Text = "⚡ Disconnect"
        $Controls.PreflightButton.Background = Get-NcsBrush -Color "#16825d"
        $Controls.PreflightButton.ToolTip = "Disconnect from remote host"
    } else {
        $Controls.PreflightButtonText.Text = "⚡ Connect"
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
    $Settings.SshPassword = $Controls.SshPasswordBox.Password
    $Settings.RemoteRepoPath = $Controls.RemoteRepoPathTextBox.Text.Trim()
    $Settings.SmbShareName = $Controls.SmbShareNameTextBox.Text.Trim()
    $Settings.SmbUser = $Controls.SmbUserTextBox.Text.Trim()
    $Settings.ReportDeliveryMode = [string] $Controls.ReportDeliveryModeComboBox.SelectedItem
    $refreshText = $Controls.AutoRefreshIntervalTextBox.Text.Trim()
    $parsedRefresh = 0
    if ([string]::IsNullOrWhiteSpace($refreshText) -or -not [int]::TryParse($refreshText, [ref] $parsedRefresh)) {
        $parsedRefresh = 5
    }
    if ($parsedRefresh -lt 0) { $parsedRefresh = 0 }
    $Settings.AutoRefreshIntervalSeconds = $parsedRefresh
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
    $Controls.SshPasswordBox.Password = $Settings.SshPassword
    $Controls.RemoteRepoPathTextBox.Text = $Settings.RemoteRepoPath
    $Controls.SmbShareNameTextBox.Text = $Settings.SmbShareName
    $Controls.SmbUserTextBox.Text = $Settings.SmbUser
    $deliveryModes = [NcsReportDeliveryMode].GetEnumNames()
    $Controls.ReportDeliveryModeComboBox.ItemsSource = $deliveryModes
    if ($deliveryModes -contains $Settings.ReportDeliveryMode) {
        $Controls.ReportDeliveryModeComboBox.SelectedItem = $Settings.ReportDeliveryMode
    } else {
        $Controls.ReportDeliveryModeComboBox.SelectedItem = [NcsReportDeliveryMode]::Auto.ToString()
    }
    $Controls.AutoRefreshIntervalTextBox.Text = [string] $Settings.AutoRefreshIntervalSeconds
    Select-NcsTreeViewItem -TreeView $Controls.ActionTreeView -Tag $Settings.LastAction -FallbackToFirst

    Update-NcsSshAuthVisibility -Controls $Controls -AuthMode $Settings.SshAuthMode
}

$script:ConsoleLineCount = 0

function Get-NcsLineColor {
    param([string] $Line)

    $text = $Line -replace '^\[\d{2}:\d{2}:\d{2}\]\s*(\[stderr\]\s*)?', ''

    if ($text -match '^\s*(fatal|ERROR)' -or $text -match '\bfailed=\d*[1-9]' -or $text -match '\bunreachable=\d*[1-9]' -or $text -match '\bignored=\d*[1-9]') {
        return "#f47067"
    }
    if ($text -match '^\s*(changed):|changed=\d*[1-9]') {
        return "#d4a72c"
    }
    if ($text -match '^\s*(skipping|rescued):|skipped=\d*[1-9]' -or $text -match '\[(WARNING|DEPRECATION WARNING)\]') {
        return "#d4a72c"
    }
    if ($text -match '^(PLAY|TASK|RUNNING HANDLER) \[' -or $text -match '^PLAY RECAP') {
        return "#6cb6ff"
    }
    if ($text -match '^\s*(ok|included):' -or $text -match '\bok=\d*[1-9]') {
        return "#57ab5a"
    }
    if ($Line -match '\[stderr\]') {
        return "#f47067"
    }
    if ($text -match '^>' -or $text -match '^---') {
        return "#8e939c"
    }
    return $null
}

function Add-NcsConsoleLine {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls,
        [Parameter(Mandatory)]
        [string] $Line
    )

    $doc = $Controls.ConsoleTextBox.Document
    $para = [System.Windows.Documents.Paragraph]::new()

    if ($Line -match '^(\[\d{2}:\d{2}:\d{2}\])\s*(\[stderr\]\s*)?(.*)$') {
        $tsRun = [System.Windows.Documents.Run]::new($Matches[1] + " ")
        $tsRun.Foreground = Get-NcsBrush -Color "#555b66"
        $para.Inlines.Add($tsRun)
        if (-not [string]::IsNullOrWhiteSpace($Matches[2])) {
            $stderrTag = [System.Windows.Documents.Run]::new("[stderr] ")
            $stderrTag.Foreground = Get-NcsBrush -Color "#f47067"
            $para.Inlines.Add($stderrTag)
        }
        $bodyText = $Matches[3]
    } else {
        $bodyText = $Line
    }

    $bodyRun = [System.Windows.Documents.Run]::new($bodyText)
    $color = Get-NcsLineColor -Line $Line
    if ($null -ne $color) {
        $bodyRun.Foreground = Get-NcsBrush -Color $color
    }
    $para.Inlines.Add($bodyRun)
    $doc.Blocks.Add($para)

    $script:ConsoleLineCount++
    if ($script:ConsoleLineCount -gt 8500) {
        while ($doc.Blocks.Count -gt 8000) {
            $doc.Blocks.Remove($doc.Blocks.FirstBlock)
        }
        $script:ConsoleLineCount = $doc.Blocks.Count
    }
}

$script:_CachedConsoleScrollViewer = $null

function Sync-NcsConsoleScroll {
    param(
        [Parameter(Mandatory)]
        [hashtable] $Controls
    )

    $sv = $script:_CachedConsoleScrollViewer
    if ($null -eq $sv) {
        $rtb = $Controls.ConsoleTextBox
        if ([System.Windows.Media.VisualTreeHelper]::GetChildrenCount($rtb) -eq 0) {
            $rtb.ScrollToEnd()
            return
        }
        $sv = [System.Windows.Media.VisualTreeHelper]::GetChild($rtb, 0)
        while ($null -ne $sv -and $sv -isnot [System.Windows.Controls.ScrollViewer]) {
            if ([System.Windows.Media.VisualTreeHelper]::GetChildrenCount($sv) -eq 0) { break }
            $sv = [System.Windows.Media.VisualTreeHelper]::GetChild($sv, 0)
        }
        if ($null -eq $sv -or $sv -isnot [System.Windows.Controls.ScrollViewer]) {
            $rtb.ScrollToEnd()
            return
        }
        $script:_CachedConsoleScrollViewer = $sv
    }
    $atBottom = ($sv.VerticalOffset + $sv.ViewportHeight) -ge ($sv.ExtentHeight - 50)
    if ($atBottom) {
        $Controls.ConsoleTextBox.ScrollToEnd()
    }
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

function Resolve-NcsReportRelativePath {
    param(
        [Parameter(Mandatory)]
        [string] $CacheRoot,
        [uri] $Uri,
        [string] $UncRoot = ""
    )

    if ($null -eq $Uri -or -not $Uri.IsFile) {
        return $null
    }

    $targetPath = [IO.Path]::GetFullPath($Uri.LocalPath)
    $comparison = [System.StringComparison]::OrdinalIgnoreCase

    # Check UNC root first (SMB mode)
    if (-not [string]::IsNullOrWhiteSpace($UncRoot)) {
        $uncRootPath = [IO.Path]::GetFullPath($UncRoot)
        $uncRootWithSeparator = $uncRootPath.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
        if ($targetPath.StartsWith($uncRootWithSeparator, $comparison)) {
            return $targetPath.Substring($uncRootWithSeparator.Length).Replace([IO.Path]::DirectorySeparatorChar, '/')
        }
        if ($targetPath.Equals($uncRootPath, $comparison)) {
            return ""
        }
    }

    # Check local cache root (SCP mode)
    $cacheRootPath = [IO.Path]::GetFullPath($CacheRoot)
    $cacheRootWithSeparator = $cacheRootPath.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar

    if ($targetPath.StartsWith($cacheRootWithSeparator, $comparison)) {
        return $targetPath.Substring($cacheRootWithSeparator.Length).Replace([IO.Path]::DirectorySeparatorChar, '/')
    }

    if ($targetPath.Equals($cacheRootPath, $comparison)) {
        return ""
    }

    return $null
}

function Show-NcsConsoleApp {
    param(
        [Parameter(Mandatory)]
        [string] $ProjectRoot
    )

    Import-NcsWpfAssemblies -ProjectRoot $ProjectRoot

    $script:NcsWorkerPool = $null
    try {
        $script:NcsWorkerPool = Initialize-NcsWorkerPool -ModuleRoot (Join-Path -Path $ProjectRoot -ChildPath "Modules")
    } catch {
        Write-Warning "Async worker pool unavailable: $($_.Exception.Message). Tag fetches will run synchronously."
    }

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
        WebViewUserDataRoot = $(if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
                Join-Path -Path $env:LOCALAPPDATA -ChildPath "NcsConsole/WebView2"
            } else {
                Join-Path -Path ([System.IO.Path]::GetTempPath()) -ChildPath "NcsConsole/WebView2"
            })
        ReportUncRoot       = $null
        ReportSource        = [NcsReportSource]::Unavailable
        AutoRefreshTimer    = $null
        LastReportWriteTime = [datetime]::MinValue
    }

    $reportViewState = [pscustomobject]@{
        Control             = $null
        IsInitialized       = $false
        IsInitializing      = $false
        PendingLocalPath    = ""
        PendingSourceUri    = $null
        PendingRelativePath = ""
    }

    $script:ActionGroups = @()

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

    $setReportStatus = {
        param(
            [string] $Message,
            [bool] $ShowPlaceholder = $true
        )

        $controls.ReportPlaceholder.Text = $Message
        $controls.ReportPlaceholderPanel.Visibility = if ($ShowPlaceholder) { "Visible" } else { "Collapsed" }
    }

    $openReportExternally = {
        param(
            [Parameter(Mandatory)]
            [string] $LocalReportPath,
            [string] $Reason
        )

        $status = if ([string]::IsNullOrWhiteSpace($Reason)) {
            "Opened report in default browser: $script:CurrentReportPath"
        } else {
            "Embedded reports unavailable. Opened in default browser: $Reason"
        }

        & $setReportStatus $status $true
        Start-Process -FilePath $LocalReportPath | Out-Null
    }

    $ensureReportBrowser = {
        if (-not $script:NcsWebView2Available -or $null -eq $reportViewState.Control) {
            return $false
        }

        if ($reportViewState.IsInitialized) {
            return $true
        }

        if ($reportViewState.IsInitializing) {
            return $false
        }

        try {
            $reportViewState.IsInitializing = $true

            # Verify the runtime is actually detectable
            try {
                $rtVersion = [Microsoft.Web.WebView2.Core.CoreWebView2Environment]::GetAvailableBrowserVersionString()
            } catch {
                $reportViewState.IsInitializing = $false
                $innerMsg = $_.Exception.InnerException.Message ?? $_.Exception.Message
                $script:NcsWebView2Status = "WebView2 Runtime not detected ($innerMsg). If already installed, try: winget install Microsoft.EdgeWebView2Runtime --scope machine (as admin)"
                return $false
            }

            if (-not (Test-Path -LiteralPath $state.WebViewUserDataRoot)) {
                [System.IO.Directory]::CreateDirectory($state.WebViewUserDataRoot) | Out-Null
            }
            $environment = [Microsoft.Web.WebView2.Core.CoreWebView2Environment]::CreateAsync($null, $state.WebViewUserDataRoot).GetAwaiter().GetResult()
            $null = $reportViewState.Control.EnsureCoreWebView2Async($environment)
        } catch {
            $reportViewState.IsInitializing = $false
            $script:NcsWebView2Status = "WebView2 init failed (runtime $rtVersion): $($_.Exception.Message)"
        }

        return $false
    }

    if ($script:NcsWebView2Available) {
        try {
            $reportWebView = [Microsoft.Web.WebView2.Wpf.WebView2]::new()
            $reportWebView.HorizontalAlignment = "Stretch"
            $reportWebView.VerticalAlignment = "Stretch"
            $reportViewState.Control = $reportWebView
            $controls.ReportHost.Children.Add($reportWebView) | Out-Null

            $reportWebView.Add_CoreWebView2InitializationCompleted({
                param($s, $e)

                $reportViewState.IsInitializing = $false
                if ($e.IsSuccess) {
                    $reportViewState.IsInitialized = $true
                    if ($null -ne $reportViewState.PendingSourceUri) {
                        $s.Source = $reportViewState.PendingSourceUri
                        $reportViewState.PendingSourceUri = $null
                    }
                    return
                }

                $script:NcsWebView2Status = "WebView2 runtime unavailable: $($e.InitializationException.Message)"
                $pendingLocalPath = $reportViewState.PendingLocalPath
                $reportViewState.PendingSourceUri = $null
                $reportViewState.PendingLocalPath = ""
                $reportViewState.PendingRelativePath = ""
                if (-not [string]::IsNullOrWhiteSpace($pendingLocalPath) -and (Test-Path -LiteralPath $pendingLocalPath)) {
                    & $openReportExternally $pendingLocalPath $script:NcsWebView2Status
                } else {
                    & $setReportStatus $script:NcsWebView2Status $true
                }
            })

            $reportWebView.Add_NavigationStarting({
                param($_sender, $e)

                $targetUri = $null
                if (-not [string]::IsNullOrWhiteSpace($e.Uri)) {
                    try {
                        $targetUri = [uri] $e.Uri
                    } catch {
                        $targetUri = $null
                    }
                }

                $relativePath = Resolve-NcsReportRelativePath -CacheRoot $state.ReportCacheRoot -Uri $targetUri -UncRoot ($state.ReportUncRoot ?? "")
                if ($null -ne $relativePath) {
                    if (-not [string]::IsNullOrWhiteSpace($reportViewState.PendingRelativePath) -and $reportViewState.PendingRelativePath -eq $relativePath) {
                        $reportViewState.PendingRelativePath = ""
                        $reportViewState.PendingLocalPath = ""
                        & $setReportStatus "" $false
                        return
                    }

                    if (-not [string]::IsNullOrWhiteSpace($script:CurrentReportPath) -and $script:CurrentReportPath -ne $relativePath) {
                        $script:ReportHistory.Add($script:CurrentReportPath)
                    }
                    $script:CurrentReportPath = $relativePath
                    $controls.ReportBackButton.IsEnabled = $script:ReportHistory.Count -gt 0
                    & $setReportStatus "" $false
                    return
                }

                if ($targetUri -and $targetUri.IsAbsoluteUri) {
                    $e.Cancel = $true
                    Start-Process -FilePath $targetUri.AbsoluteUri | Out-Null
                    & $setReportStatus "Opened external link in default browser: $($targetUri.AbsoluteUri)" $true
                }
            })
        } catch {
            $script:NcsWebView2Available = $false
            $script:NcsWebView2Status = "WebView2 control failed to initialize: $($_.Exception.Message)"
        }
    }

    if (-not $script:NcsWebView2Available) {
        & $setReportStatus "Connect to sync reports. Inline viewing unavailable: $script:NcsWebView2Status" $true
    } else {
        & $setReportStatus "Connect to sync reports to view them inline" $true
    }

    $durationTimer = [System.Windows.Threading.DispatcherTimer]::new()
    $durationTimer.Interval = [timespan]::FromSeconds(1)
    $durationTimer.Add_Tick({
        if ($state.CurrentHandle) {
            $elapsed = (Get-Date) - $state.CurrentHandle.StartedAt
            $controls.DurationTextBlock.Text = Format-NcsDuration -Duration $elapsed
        }
    })

    $autoRefreshTimer = [System.Windows.Threading.DispatcherTimer]::new()
    $autoRefreshInterval = [Math]::Max($state.Settings.AutoRefreshIntervalSeconds, 1)
    if ($state.Settings.ReportDeliveryMode -eq [NcsReportDeliveryMode]::Scp -or
        ($state.Settings.ReportDeliveryMode -eq [NcsReportDeliveryMode]::Auto -and $state.ReportSource -eq [NcsReportSource]::Scp)) {
        $autoRefreshInterval = [Math]::Max($autoRefreshInterval, 30)
    }
    $autoRefreshTimer.Interval = [TimeSpan]::FromSeconds($autoRefreshInterval)
    $autoRefreshTimer.Add_Tick({
        if ([string]::IsNullOrWhiteSpace($script:CurrentReportPath)) { return }
        if (-not $state.PreflightResult -or -not $state.PreflightResult.IsReady) { return }

        try {
            if ($state.ReportSource -eq [NcsReportSource]::Smb -and -not [string]::IsNullOrWhiteSpace($state.ReportUncRoot)) {
                $filePath = Join-Path -Path $state.ReportUncRoot -ChildPath ($script:CurrentReportPath -replace '/', '\')
            } elseif ($state.ReportSource -eq [NcsReportSource]::Scp) {
                # Re-sync via SCP before checking
                $script:ReportsSynced = $false
                $mirror = Invoke-NcsReportMirror -Settings $state.Settings -LocalRoot $state.ReportCacheRoot
                if ($mirror.ExitCode -ne 0) { return }
                $script:ReportsSynced = $true
                $filePath = Join-Path -Path $state.ReportCacheRoot -ChildPath ($script:CurrentReportPath -replace '/', [System.IO.Path]::DirectorySeparatorChar)
            } else {
                return
            }

            if (-not (Test-Path -LiteralPath $filePath)) { return }

            $currentWriteTime = (Get-Item -LiteralPath $filePath).LastWriteTimeUtc
            if ($currentWriteTime -gt $state.LastReportWriteTime) {
                $state.LastReportWriteTime = $currentWriteTime
                if ($null -ne $reportViewState.Control -and $null -ne $reportViewState.Control.Source) {
                    $reportViewState.Control.Reload()
                }
            }
        } catch {
            # Silently ignore — file may be mid-write
        }
    })
    $state.AutoRefreshTimer = $autoRefreshTimer

    $refreshPreview = {
        Update-NcsCommandPreview -Controls $controls -Settings $state.Settings
    }

    $script:TagFetchTokens = @{}
    $script:TagFetchInFlight = @{}

    $populatePlaybookTags = {
        param(
            [string] $Playbook,
            [string] $TreeName,
            [string] $EmptyTextName,
            [string] $EmptyMessage = "Select a playbook to load tags"
        )
        $localControls = $controls
        $localState = $state
        $tree = $localControls[$TreeName]
        $emptyText = $localControls[$EmptyTextName]
        $tree.Items.Clear()
        if ([string]::IsNullOrWhiteSpace($Playbook)) {
            $emptyText.Text = $EmptyMessage
            $emptyText.Visibility = "Visible"
            return
        }
        $applyGroups = {
            param($Controls, [string] $TreeName, [string] $EmptyTextName, $Groups)
            $et = $Controls[$EmptyTextName]
            # PS unwraps empty arrays pulled out of hashtables to $null, and
            # @($null).Length is 1, so guard explicitly.
            $list = @()
            if ($null -ne $Groups) { $list = @($Groups) | Where-Object { $null -ne $_ } }
            $tree = $Controls[$TreeName]
            $tree.Items.Clear()
            if (@($list).Count -gt 0) {
                Build-NcsTreeView -Controls $Controls -TreeViewName $TreeName -Groups $list -TagProperty "tag" -Expanded $true -LeafIcon ""
                $et.Visibility = "Collapsed"
            } else {
                $et.Text = "No --tags declared in this playbook"
                $et.Visibility = "Visible"
            }
        }
        if ($script:PlaybookTagsCache.ContainsKey($Playbook)) {
            & $applyGroups $localControls $TreeName $EmptyTextName $script:PlaybookTagsCache[$Playbook]
            return
        }
        $token = [guid]::NewGuid().ToString('N')
        $script:TagFetchTokens[$TreeName] = $token
        $emptyText.Text = "Loading tags…"
        $emptyText.Visibility = "Visible"

        if ($null -eq $script:NcsWorkerPool) {
            # Worker pool unavailable — run synchronously (UI blocks briefly).
            try {
                $script:PlaybookTagsCache[$Playbook] = Get-NcsRemotePlaybookTags -Settings $localState.Settings -Playbook $Playbook
            } catch {
                $script:PlaybookTagsCache[$Playbook] = @()
            }
            & $applyGroups $localControls $TreeName $EmptyTextName $script:PlaybookTagsCache[$Playbook]
            return
        }

        $settingsHash = ConvertTo-NcsSettingsHashtable -Settings $localState.Settings
        $ps = [powershell]::Create()
        $ps.RunspacePool = $script:NcsWorkerPool
        [void] $ps.AddScript({
            param($settingsHash, $playbook)
            $settings = [NcsConsoleSettings]::new()
            $applied = @()
            $failed = @()
            foreach ($key in $settingsHash.Keys) {
                try { $settings.$key = $settingsHash[$key]; $applied += $key }
                catch { $failed += "$key=$($_.Exception.Message)" }
            }
            try {
                $groups = @(Get-NcsRemotePlaybookTags -Settings $settings -Playbook $playbook)
                if (@($groups).Count -eq 0) {
                    $safe = $playbook -replace "[^A-Za-z0-9._/-]", ""
                    $cmd = New-NcsRepoShellCommand -Settings $settings -Command "ansible-playbook --list-tags '$safe' 2>&1"
                    $probe = Invoke-NcsSshProbe -Settings $settings -RemoteCommand $cmd
                    $stdoutHead = if ($probe.StdOut) { $probe.StdOut.Substring(0, [Math]::Min(240, $probe.StdOut.Length)) } else { "" }
                    $stderrHead = if ($probe.StdErr) { $probe.StdErr.Substring(0, [Math]::Min(240, $probe.StdErr.Length)) } else { "" }
                    Write-Error ("diag host={0} user={1} auth={2} exit={3} stdout={4} stderr={5} applied={6} failed={7}" -f $settings.SshHost, $settings.SshUser, $settings.SshAuthMode, $probe.ExitCode, ($stdoutHead -replace "`r?`n", "|"), ($stderrHead -replace "`r?`n", "|"), ($applied -join ","), ($failed -join ";"))
                }
                , $groups
            } catch {
                Write-Error ("worker exception: {0}" -f $_.Exception.Message)
                , @()
            }
        })
        [void] $ps.AddArgument($settingsHash)
        [void] $ps.AddArgument($Playbook)
        $asyncResult = $ps.BeginInvoke()

        $pollTimer = [System.Windows.Threading.DispatcherTimer]::new()
        $pollTimer.Interval = [TimeSpan]::FromMilliseconds(100)
        $pollTimer.Tag = $token
        $script:TagFetchInFlight[$token] = [pscustomobject]@{
            PS            = $ps
            AsyncResult   = $asyncResult
            Token         = $token
            TreeName      = $TreeName
            EmptyTextName = $EmptyTextName
            Playbook      = $Playbook
            Controls      = $localControls
            ApplyGroups   = $applyGroups
            Timer         = $pollTimer
        }
        $pollTimer.Add_Tick({
            param($sender, $_e)
            $key = [string] $sender.Tag
            if (-not $script:TagFetchInFlight.ContainsKey($key)) { $sender.Stop(); return }
            $entry = $script:TagFetchInFlight[$key]
            if (-not $entry.AsyncResult.IsCompleted) { return }
            $sender.Stop()
            [void] $script:TagFetchInFlight.Remove($key)
            $groups = @()
            $endInvokeError = $null
            try {
                $result = $entry.PS.EndInvoke($entry.AsyncResult)
                if ($null -ne $result -and $result.Count -gt 0 -and $null -ne $result[0]) {
                    $groups = @($result[0])
                }
            } catch {
                $endInvokeError = $_.Exception.Message
                $groups = @()
            } finally {
                try {
                    foreach ($err in $entry.PS.Streams.Error) {
                        Add-NcsConsoleLine -Controls $entry.Controls -Line "[tag-fetch $($entry.Playbook)] $err"
                    }
                } catch { $null = $_ }
                try { $entry.PS.Dispose() } catch { $null = $_ }
            }
            if ($null -ne $endInvokeError) {
                Add-NcsConsoleLine -Controls $entry.Controls -Line "[tag-fetch $($entry.Playbook)] EndInvoke: $endInvokeError"
            }
            if (@($groups).Count -eq 0) {
                Add-NcsConsoleLine -Controls $entry.Controls -Line "[tag-fetch $($entry.Playbook)] returned no tags"
            }
            if (-not $script:TagFetchTokens.ContainsKey($entry.TreeName)) { return }
            if ($script:TagFetchTokens[$entry.TreeName] -ne $entry.Token) { return }
            $script:PlaybookTagsCache[$entry.Playbook] = $groups
            & $entry.ApplyGroups $entry.Controls $entry.TreeName $entry.EmptyTextName $groups
        })
        $pollTimer.Start()
    }

    $invalidatePreflight = {
        $state.PreflightResult = $null
        Set-NcsPreflightState -Controls $controls -State "Not Connected"
    }

    & $refreshPreview

    $controls.ActionTreeView.Add_PreviewMouseWheel({
        param($_sender, $e)
        $controls.ActionScrollViewer.ScrollToVerticalOffset($controls.ActionScrollViewer.VerticalOffset - $e.Delta / 3)
        $e.Handled = $true
    })

    $controls.ActionTreeView.Add_SelectedItemChanged({
        param($_sender, $e)
        $item = $e.NewValue
        $playbook = ""
        $label = "Select a playbook"
        if ($null -ne $item -and -not [string]::IsNullOrWhiteSpace($item.Tag)) {
            $state.Settings.LastAction = $item.Tag
            $playbook = $item.Tag
            $label = if ($item.ToolTip) { [string] $item.ToolTip } else { [string] $item.Tag }
        }
        $controls.ActionSelectionTitle.Text = $label
        $controls.ActionPropertiesPanel.Visibility = if ([string]::IsNullOrWhiteSpace($playbook)) { "Collapsed" } else { "Visible" }
        $matchedAction = if (-not [string]::IsNullOrWhiteSpace($playbook) -and $script:ActionItemMap.ContainsKey($playbook)) { $script:ActionItemMap[$playbook] } else { $null }
        $isMutating = $null -ne $matchedAction -and $matchedAction.ContainsKey('mutating') -and $matchedAction['mutating'] -eq $true
        $controls.MutatingWarning.Visibility = if ($isMutating) { "Visible" } else { "Collapsed" }
        Update-NcsActionOptions -Controls $controls -ActionItem $matchedAction
        & $populatePlaybookTags $playbook "ActionTagsTree" "ActionTagsEmptyText"
        & $refreshPreview
    })

    Register-NcsLimitPicker `
        -TextBox $controls.ActionLimitTextBox `
        -Tree $controls.ActionLimitTree `
        -ScrollViewer $controls.ActionLimitTreeScroll `
        -OnChanged { & $refreshPreview }

    Register-NcsLimitPicker -Simple `
        -TextBox $controls.ActionTagsTextBox `
        -Tree $controls.ActionTagsTree `
        -ScrollViewer $controls.ActionTagsTreeScroll `
        -OnChanged { & $refreshPreview }

    Register-NcsLimitPicker `
        -TextBox $controls.ScheduleLimitTextBox `
        -Tree $controls.ScheduleLimitTree `
        -ScrollViewer $controls.ScheduleLimitTreeScroll

    Register-NcsLimitPicker -Simple `
        -TextBox $controls.ScheduleTagsTextBox `
        -Tree $controls.ScheduleTagsTree `
        -ScrollViewer $controls.ScheduleTagsTreeScroll
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
        param($_sender, $e)

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
        } catch [System.InvalidOperationException] {
            $null = $_ # DragMove throws if mouse released during call
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

    $controls.PlaybooksCloseButton.Add_Click({ & $closeOperate })

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

    $reportsColumn = $controls.ReportsColumn
    $schedulesColumn = $controls.SchedulesColumn
    $script:ReportHistory = [System.Collections.Generic.List[string]]::new()
    $script:CurrentReportPath = ""
    $script:ReportsSynced = $false

    $resolveReportSource = {
        $mode = $state.Settings.ReportDeliveryMode
        if ($mode -eq [NcsReportDeliveryMode]::Scp) {
            $state.ReportSource = [NcsReportSource]::Scp
            $state.ReportUncRoot = $null
            return
        }

        if (-not [string]::IsNullOrWhiteSpace($state.Settings.SmbUser) -and [string]::IsNullOrWhiteSpace($state.Settings.SmbPassword)) {
            $pw = Show-NcsPasswordPrompt -Owner $window -Title "SMB Password" -Prompt "Enter password for SMB user '$($state.Settings.SmbUser)':"
            if ($null -eq $pw) {
                if ($mode -eq [NcsReportDeliveryMode]::Smb) {
                    $state.ReportSource = [NcsReportSource]::Unavailable
                    $state.ReportUncRoot = $null
                    & $setReportStatus "SMB password required." $true
                    return
                }
                $state.ReportSource = [NcsReportSource]::Scp
                $state.ReportUncRoot = $null
                return
            }
            $state.Settings.SmbPassword = $pw
        }

        $smb = Test-NcsSmbAccess -Settings $state.Settings
        if ($smb.Accessible) {
            $state.ReportSource = [NcsReportSource]::Smb
            $state.ReportUncRoot = $smb.UncRoot
            return
        }

        # Force re-prompt on next attempt — stale creds are the most likely cause.
        $state.Settings.SmbPassword = ""

        if ($mode -eq [NcsReportDeliveryMode]::Smb) {
            $state.ReportSource = [NcsReportSource]::Unavailable
            $state.ReportUncRoot = $null
            & $setReportStatus "SMB share unreachable: $($smb.Error)" $true
            return
        }

        $state.ReportSource = [NcsReportSource]::Scp
        $state.ReportUncRoot = $null
    }

    $syncReports = {
        if ($script:ReportsSynced) { return $true }
        if (-not $state.PreflightResult -or -not $state.PreflightResult.IsReady) { return $false }

        & $resolveReportSource

        if ($state.ReportSource -eq [NcsReportSource]::Smb) {
            $script:ReportsSynced = $true
            return $true
        }

        if ($state.ReportSource -eq [NcsReportSource]::Unavailable) {
            return $false
        }

        $mirror = Invoke-NcsReportMirror -Settings $state.Settings -LocalRoot $state.ReportCacheRoot
        if ($mirror.ExitCode -eq 0) {
            $script:ReportsSynced = $true
            return $true
        }
        $message = @($mirror.StdErr, $mirror.StdOut) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -First 1
        if ([string]::IsNullOrWhiteSpace($message)) { $message = "scp.exe failed to mirror reports." }
        & $setReportStatus $message.Trim() $true
        return $false
    }

    $loadReport = {
        param([string] $RelativePath)
        if (-not $state.PreflightResult -or -not $state.PreflightResult.IsReady) { return }
        try {
            if (-not (& $syncReports)) { return }

            if ($state.ReportSource -eq [NcsReportSource]::Smb) {
                $reportFilePath = Join-Path -Path $state.ReportUncRoot -ChildPath ($RelativePath -replace '/', '\')
            } else {
                $reportFilePath = Join-Path -Path $state.ReportCacheRoot -ChildPath ($RelativePath -replace '/', [System.IO.Path]::DirectorySeparatorChar)
            }

            if (-not (Test-Path -LiteralPath $reportFilePath)) {
                & $setReportStatus "Report not found: $RelativePath" $true
                return
            }

            if (-not [string]::IsNullOrWhiteSpace($script:CurrentReportPath) -and $script:CurrentReportPath -ne $RelativePath) {
                $script:ReportHistory.Add($script:CurrentReportPath)
            }
            $script:CurrentReportPath = $RelativePath
            $state.LastReportWriteTime = (Get-Item -LiteralPath $reportFilePath).LastWriteTimeUtc
            $controls.ReportBackButton.IsEnabled = $script:ReportHistory.Count -gt 0

            $browserReady = & $ensureReportBrowser
            if ($browserReady -or $reportViewState.IsInitializing) {
                $reportViewState.PendingRelativePath = $RelativePath
                $reportViewState.PendingLocalPath = $reportFilePath
                $reportViewState.PendingSourceUri = [uri] $reportFilePath
                & $setReportStatus "Loading report: $RelativePath" $true
                if ($browserReady) {
                    $reportViewState.Control.Source = $reportViewState.PendingSourceUri
                }
            } else {
                & $openReportExternally $reportFilePath $script:NcsWebView2Status
            }
        } catch {
            & $setReportStatus $_.Exception.Message $true
        }
    }

    $openReports = {
        $reportsColumn.Width = [System.Windows.GridLength]::new(1, [System.Windows.GridUnitType]::Star)
        $reportsColumn.MinWidth = 0
        $controls.ReportsPane.Visibility = "Visible"
        $controls.ReportsSplitter.Visibility = "Visible"
        Update-NcsTopTabState -Controls $controls
        if ([string]::IsNullOrWhiteSpace($script:CurrentReportPath) -and $state.PreflightResult -and $state.PreflightResult.IsReady) {
            & $loadReport $script:DefaultReportPath
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

    $script:ReportsMaximized = $false
    $script:PreMaximizeState = $null

    $controls.ReportsMaximizeButton.Add_Click({
        if ($script:ReportsMaximized) {
            $prev = $script:PreMaximizeState
            if ($prev.OperateVisible) {
                $operateColumn.Width = $prev.OperateWidth
                $controls.OperateContent.Visibility = "Visible"
            }
            if ($prev.ConsoleVisible) {
                $consoleColumn.Width = $prev.ConsoleWidth
                $controls.ConsolePane.Visibility = "Visible"
                $controls.ConsoleSplitter.Visibility = "Visible"
            }
            if ($prev.SettingsVisible) {
                $settingsColumn.Width = $prev.SettingsWidth
                $controls.SettingsPanel.Visibility = "Visible"
                $controls.SettingsSplitter.Visibility = "Visible"
            }
            if ($prev.SchedulesVisible) {
                $schedulesColumn.Width = $prev.SchedulesWidth
                $controls.SchedulesPane.Visibility = "Visible"
                $controls.SchedulesSplitter.Visibility = "Visible"
            }
            $script:ReportsMaximized = $false
            $controls.ReportsMaximizeButton.ToolTip = "Maximize reports"
        } else {
            $script:PreMaximizeState = @{
                OperateVisible    = $controls.OperateContent.Visibility -eq "Visible"
                OperateWidth      = $operateColumn.Width
                ConsoleVisible    = $controls.ConsolePane.Visibility -eq "Visible"
                ConsoleWidth      = $consoleColumn.Width
                SettingsVisible   = $controls.SettingsPanel.Visibility -eq "Visible"
                SettingsWidth     = $settingsColumn.Width
                SchedulesVisible  = $controls.SchedulesPane.Visibility -eq "Visible"
                SchedulesWidth    = $schedulesColumn.Width
            }
            & $closeOperate
            & $closeConsole
            & $closeSettings
            & $closeSchedules
            $script:ReportsMaximized = $true
            $controls.ReportsMaximizeButton.ToolTip = "Restore panels"
        }
        Update-NcsTopTabState -Controls $controls
    })

    $controls.ReportsToggleButton.Add_Click({
        if ($controls.ReportsPane.Visibility -eq "Visible") {
            & $closeReports
        } else {
            & $openReports
        }
    })

    $controls.ReportHomeButton.Add_Click({
        & $loadReport $script:DefaultReportPath
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
        $script:ReportsSynced = $false
        $state.LastReportWriteTime = [datetime]::MinValue
        if (-not [string]::IsNullOrWhiteSpace($script:CurrentReportPath)) {
            $path = $script:CurrentReportPath
            $script:CurrentReportPath = ""
            & $loadReport $path
        } else {
            & $loadReport $script:DefaultReportPath
        }
    })

    # -------------------------------------------------------------------------
    # Schedules panel
    # -------------------------------------------------------------------------
    $script:ScheduleEntries = [System.Collections.Generic.List[NcsScheduleEntry]]::new()
    $script:EditingScheduleIndex = -1
    $script:ActionItemMap = @{}
    $script:PlaybookTagsCache = @{}
    $script:SchedulesLoaded = $false

    $openSchedules = {
        $schedulesColumn.Width = [System.Windows.GridLength]::new(1, [System.Windows.GridUnitType]::Star)
        $schedulesColumn.MinWidth = 0
        $controls.SchedulesPane.Visibility = "Visible"
        $controls.SchedulesSplitter.Visibility = "Visible"
        Update-NcsTopTabState -Controls $controls
        if (-not $script:SchedulesLoaded) {
            & $loadSchedules
        }
    }

    $closeSchedules = {
        $controls.SchedulesPane.Visibility = "Collapsed"
        $controls.SchedulesSplitter.Visibility = "Collapsed"
        $schedulesColumn.Width = [System.Windows.GridLength]::new(0)
        $schedulesColumn.MinWidth = 0
        Update-NcsTopTabState -Controls $controls
    }

    $controls.SchedulesToggleButton.Add_Click({
        if ($controls.SchedulesPane.Visibility -eq "Visible") {
            & $closeSchedules
        } else {
            & $openSchedules
        }
    })

    $controls.SchedulesCloseButton.Add_Click({ & $closeSchedules })

    $refreshScheduleList = {
        param($TimerStatus)
        $items = [System.Collections.Generic.List[object]]::new()
        foreach ($entry in $script:ScheduleEntries) {
            if ($null -ne $TimerStatus) {
                if ($TimerStatus.ContainsKey($entry.Name)) {
                    $ts = $TimerStatus[$entry.Name]
                    $entry.NextTrigger = $ts.Next
                    $entry.LastTrigger = $ts.Last
                    if ($ts.ContainsKey("LastResult")) { $entry.LastResult = $ts.LastResult }
                } else {
                    $entry.NextTrigger = ""
                    $entry.LastTrigger = ""
                }
            }
            $items.Add([pscustomobject]@{
                EnabledIcon = if ($entry.Enabled) { [char]0x2713 } else { "" }
                Name        = $entry.Name
                Playbook    = $entry.Playbook
                Calendar    = $entry.Calendar
                NextTrigger = $entry.NextTrigger
                LastTrigger = $entry.LastTrigger
                LastResult  = $entry.LastResult
            })
        }
        $controls.ScheduleListView.ItemsSource = $items
    }

    $loadSchedules = {
        if (-not $state.PreflightResult -or -not $state.PreflightResult.IsReady) { return }

        try {
            $snapshot = Get-NcsRemoteScheduleSnapshot -Settings $state.Settings
            $script:ScheduleEntries = [System.Collections.Generic.List[NcsScheduleEntry]]::new(
                [NcsScheduleEntry[]]$snapshot.Schedules
            )
            & $refreshScheduleList $snapshot.TimerStatus
            $controls.SchedulePlaceholder.Visibility = "Collapsed"
            $controls.ScheduleListView.Visibility = "Visible"
            $script:SchedulesLoaded = $true
        } catch {
            $controls.SchedulePlaceholder.Text = "Failed to load schedules: $($_.Exception.Message)"
        }
    }

    $controls.ScheduleRefreshButton.Add_Click({ & $loadSchedules })

    $populatePlaybookCombo = {
        param([string] $Include)
        $controls.SchedulePlaybookComboBox.ItemsSource = @(Get-NcsSchedulePlaybookChoices -ScheduleEntries $script:ScheduleEntries -BaseChoices @($script:ActionItemMap.Keys) -Include $Include)
    }

    $populateTagsTree = {
        param([string] $Playbook)
        & $populatePlaybookTags $Playbook "ScheduleTagsTree" "ScheduleTagsEmptyText"
    }

    $showScheduleEditForm = {
        param([int] $Index)
        $script:EditingScheduleIndex = $Index
        $isEdit = ($Index -ge 0 -and $Index -lt $script:ScheduleEntries.Count)
        $src = if ($isEdit) { $script:ScheduleEntries[$Index] } else { [NcsScheduleEntry]::new() }

        $controls.ScheduleEditTitle.Text = if ($isEdit) { "Edit Schedule" } else { "New Schedule" }
        $controls.ScheduleNameTextBox.Text = $src.Name
        $controls.ScheduleNameTextBox.IsReadOnly = $isEdit
        $controls.ScheduleCalendarTextBox.Text = $src.Calendar
        $controls.ScheduleDescriptionTextBox.Text = $src.Description
        $controls.ScheduleLimitTextBox.Text = $src.Limit
        $controls.ScheduleTagsTextBox.Text = $src.Tags
        $controls.ScheduleTimeoutTextBox.Text = [string]$src.TimeoutMinutes
        $controls.ScheduleExtraArgsTextBox.Text = $src.ExtraArgs
        $controls.ScheduleEnabledCheckBox.IsChecked = $src.Enabled
        $controls.ScheduleCheckModeCheckBox.IsChecked = $src.CheckMode
        $controls.ScheduleNotifyCheckBox.IsChecked = $src.NotifyOnFailure
        $controls.ScheduleDeleteButton.Visibility = if ($isEdit) { "Visible" } else { "Collapsed" }

        & $populatePlaybookCombo $src.Playbook
        if ($isEdit) {
            $controls.SchedulePlaybookComboBox.SelectedItem = $src.Playbook
        } else {
            $controls.SchedulePlaybookComboBox.SelectedIndex = -1
        }
        & $populateTagsTree $src.Playbook

        $controls.ScheduleEditPanel.Visibility = "Visible"
    }

    $controls.SchedulePlaybookComboBox.Add_SelectionChanged({
        $selected = [string] $controls.SchedulePlaybookComboBox.SelectedItem
        if ($script:EditingScheduleIndex -ne -1 -or $controls.ScheduleEditPanel.Visibility -eq "Visible") {
            & $populateTagsTree $selected
        }
    }.GetNewClosure())

    $hideScheduleEditForm = {
        $controls.ScheduleEditPanel.Visibility = "Collapsed"
        $script:EditingScheduleIndex = -1
    }

    $controls.ScheduleAddButton.Add_Click({
        & $showScheduleEditForm -1
    })

    $controls.ScheduleCancelButton.Add_Click({
        & $hideScheduleEditForm
    })

    $controls.ScheduleListView.Add_SelectionChanged({
        $idx = $controls.ScheduleListView.SelectedIndex
        if ($idx -lt 0 -or $idx -eq $script:EditingScheduleIndex) { return }
        & $showScheduleEditForm $idx
    }.GetNewClosure())

    $controls.ScheduleDeleteButton.Add_Click({
        $idx = $script:EditingScheduleIndex
        if ($idx -ge 0 -and $idx -lt $script:ScheduleEntries.Count) {
            $script:ScheduleEntries.RemoveAt($idx)
            & $hideScheduleEditForm
            & $refreshScheduleList

            $saved = Save-NcsRemoteSchedules -Settings $state.Settings -Schedules @($script:ScheduleEntries)
            if ($saved) {
                $controls.StatusTextBlock.Text = "Schedule deleted. Applying..."
                & $applySchedules
            } else {
                $controls.StatusTextBlock.Text = "Failed to save schedules to remote."
            }
        }
    }.GetNewClosure())

    $applySchedules = {
        $cmd = New-NcsRepoShellCommand -Settings $state.Settings -Command "ansible-playbook playbooks/ncs/manage_schedules.yml && $(Get-NcsTimerStatusQueryCommand)"
        $probe = Invoke-NcsSshProbe -Settings $state.Settings -RemoteCommand $cmd
        if ($probe.ExitCode -eq 0) {
            $controls.StatusTextBlock.Text = "Schedules applied successfully."
            & $refreshScheduleList (Read-NcsTimerStatusFromOutput -StdOut $probe.StdOut)
        } else {
            $errTail = if (-not [string]::IsNullOrWhiteSpace($probe.StdErr)) { " — $($probe.StdErr.Trim().Split("`n")[-1])" } else { "" }
            $controls.StatusTextBlock.Text = "Failed to apply schedules (exit $($probe.ExitCode))$errTail"
        }
    }

    $controls.ScheduleSaveButton.Add_Click({
        $name = $controls.ScheduleNameTextBox.Text.Trim()
        if ([string]::IsNullOrWhiteSpace($name)) {
            $controls.StatusTextBlock.Text = "Schedule name is required."
            return
        }
        if ($name -notmatch '^[a-z0-9]([a-z0-9-]*[a-z0-9])?$') {
            $controls.StatusTextBlock.Text = "Schedule name must be lowercase alphanumeric with hyphens."
            return
        }
        $playbook = $controls.SchedulePlaybookComboBox.SelectedItem
        if ([string]::IsNullOrWhiteSpace($playbook)) {
            $controls.StatusTextBlock.Text = "Playbook selection is required."
            return
        }
        $calendar = $controls.ScheduleCalendarTextBox.Text.Trim()
        if ([string]::IsNullOrWhiteSpace($calendar)) {
            $controls.StatusTextBlock.Text = "Calendar expression is required."
            return
        }

        $entry = [NcsScheduleEntry]::new()
        $entry.Name = $name
        $entry.Description = $controls.ScheduleDescriptionTextBox.Text.Trim()
        $entry.Playbook = $playbook
        $entry.Calendar = $calendar
        $entry.Limit = $controls.ScheduleLimitTextBox.Text.Trim()
        $entry.Tags = $controls.ScheduleTagsTextBox.Text.Trim()
        $entry.ExtraArgs = $controls.ScheduleExtraArgsTextBox.Text.Trim()
        $entry.CheckMode = $controls.ScheduleCheckModeCheckBox.IsChecked -eq $true
        $entry.Enabled = $controls.ScheduleEnabledCheckBox.IsChecked -eq $true
        $entry.NotifyOnFailure = $controls.ScheduleNotifyCheckBox.IsChecked -eq $true

        $timeout = [NcsScheduleEntry]::new().TimeoutMinutes
        if ([int]::TryParse($controls.ScheduleTimeoutTextBox.Text.Trim(), [ref]$timeout)) {
            $entry.TimeoutMinutes = $timeout
        }

        $idx = $script:EditingScheduleIndex

        if ($idx -ge 0 -and $idx -lt $script:ScheduleEntries.Count) {
            $script:ScheduleEntries[$idx] = $entry
        } else {
            $existing = $script:ScheduleEntries | Where-Object { $_.Name -eq $name }
            if ($existing) {
                $controls.StatusTextBlock.Text = "A schedule with name '$name' already exists."
                return
            }
            $script:ScheduleEntries.Add($entry)
        }

        & $hideScheduleEditForm
        & $refreshScheduleList

        $controls.StatusTextBlock.Text = "Saving schedules..."
        $saved = Save-NcsRemoteSchedules -Settings $state.Settings -Schedules @($script:ScheduleEntries)
        if ($saved) {
            $controls.StatusTextBlock.Text = "Schedules saved. Applying..."
            & $applySchedules
        } else {
            $controls.StatusTextBlock.Text = "Failed to save schedules to remote."
        }
    }.GetNewClosure())

    $controls.PreflightButton.Add_Click({
        try {
            if ($null -ne $state.PreflightResult -and $state.PreflightResult.IsReady) {
                $state.PreflightResult = $null
                Set-NcsPreflightState -Controls $controls -State "Not Connected"
                $controls.ConnectionInfoText.Text = ""
                $controls.StatusTextBlock.Text = "Disconnected."
                $controls.ActionLimitTree.Items.Clear()
                $controls.ActionLimitEmptyText.Visibility = "Visible"
                $controls.ActionTagsTree.Items.Clear()
                $controls.ActionTagsEmptyText.Visibility = "Visible"
                $controls.ScheduleLimitTree.Items.Clear()
                $controls.ScheduleLimitEmptyText.Visibility = "Visible"
                $controls.ScheduleTagsTree.Items.Clear()
                $controls.ScheduleTagsEmptyText.Visibility = "Visible"
                $script:TagFetchTokens = @{}
                Stop-NcsTagFetches
                $script:ActionGroups = @()
                $script:ActionItemMap = @{}
                $script:PlaybookTagsCache = @{}
                $controls.PlaybookSplitPane.Visibility = "Collapsed"
                $controls.PlaybookPlaceholder.Visibility = "Visible"
                $controls.RefreshPlaybooksButton.Visibility = "Collapsed"
                if ($script:NcsWebView2Available) {
                    & $setReportStatus "Connect to sync reports to view them inline" $true
                } else {
                    & $setReportStatus "Connect to sync reports. Inline viewing unavailable: $script:NcsWebView2Status" $true
                }
                $script:ReportHistory.Clear()
                $script:CurrentReportPath = ""
                $script:ReportsSynced = $false
                $state.Settings.SmbPassword = ""
                $controls.ReportBackButton.IsEnabled = $false
                if ($null -ne $state.AutoRefreshTimer) { $state.AutoRefreshTimer.Stop() }
                $state.ReportUncRoot = $null
                $state.ReportSource = [NcsReportSource]::Unavailable
                $state.LastReportWriteTime = [datetime]::MinValue
                $script:ScheduleEntries = [System.Collections.Generic.List[NcsScheduleEntry]]::new()
                $controls.SchedulePlaybookComboBox.ItemsSource = $null
                $controls.ScheduleListView.ItemsSource = $null
                $controls.ScheduleListView.Visibility = "Collapsed"
                $controls.SchedulePlaceholder.Text = "Connect to load schedules"
                $controls.SchedulePlaceholder.Visibility = "Visible"
                $controls.ScheduleEditPanel.Visibility = "Collapsed"
                return
            }

            Sync-NcsSettingsFromControls -Controls $controls -Settings $state.Settings

            if ($state.Settings.SshAuthMode -eq [NcsSshAuthMode]::KeyFile) {
                $passphrase = Show-NcsPasswordPrompt -Owner $window -Title "SSH Key Passphrase" -Prompt "Enter passphrase for SSH key (leave empty if none):" -OkLabel "Connect"
                if ($null -eq $passphrase) {
                    $controls.StatusTextBlock.Text = "Connection cancelled."
                    return
                }
                $state.Settings.SshKeyPassphrase = $passphrase
            }

            $controls.StatusTextBlock.Text = "Connecting..."
            $preflight = Test-NcsRemotePreflight -Settings $state.Settings
            $state.PreflightResult = $preflight
            if ($preflight.IsReady) {
                Set-NcsPreflightState -Controls $controls -State "Connected"
                if (-not [string]::IsNullOrWhiteSpace($preflight.Banner)) {
                    foreach ($bannerLine in ($preflight.Banner -split "`n")) {
                        Add-NcsConsoleLine -Controls $controls -Line $bannerLine.TrimEnd()
                    }
                }
                $statusParts = @("Connected.")
                try {
                    $inventoryTree = Get-NcsRemoteInventoryTree -Settings $state.Settings
                    if (@($inventoryTree).Length -gt 0) {
                        Build-NcsTreeView -Controls $controls -TreeViewName "ActionLimitTree" -Groups $inventoryTree -TagProperty "limit" -Expanded $false -LeafIcon $script:IconFolder
                        Build-NcsTreeView -Controls $controls -TreeViewName "ScheduleLimitTree" -Groups $inventoryTree -TagProperty "limit" -Expanded $false -LeafIcon $script:IconFolder
                        $controls.ActionLimitEmptyText.Visibility = "Collapsed"
                        $controls.ScheduleLimitEmptyText.Visibility = "Collapsed"
                        $statusParts += "$(@($inventoryTree).Length) inventory groups."
                    }
                } catch {
                    $statusParts += "Inventory fetch failed."
                }
                try {
                    $script:ActionGroups = Get-NcsRemotePlaybookTree -Settings $state.Settings
                    $script:ActionItemMap = Get-NcsActionItemMap -Groups $script:ActionGroups
                    if (@($script:ActionGroups).Length -eq 0) {
                        $statusParts += "No playbooks found."
                    }
                } catch {
                    $script:ActionGroups = @()
                    $script:ActionItemMap = @{}
                    $statusParts += "Playbook scan failed."
                }
                Build-NcsTreeView -Controls $controls -TreeViewName "ActionTreeView" -Groups $script:ActionGroups -TagProperty "playbook" -Expanded $true -LeafIcon $script:IconFile
                $controls.PlaybookPlaceholder.Visibility = "Collapsed"
                $controls.PlaybookSplitPane.Visibility = "Visible"
                $controls.RefreshPlaybooksButton.Visibility = "Visible"
                Select-NcsTreeViewItem -TreeView $controls.ActionTreeView -Tag $state.Settings.LastAction -FallbackToFirst
                $controls.StatusTextBlock.Text = $statusParts -join " "

                if ($state.Settings.AutoRefreshIntervalSeconds -gt 0 -and $null -ne $state.AutoRefreshTimer) {
                    $interval = [Math]::Max($state.Settings.AutoRefreshIntervalSeconds, 1)
                    if ($state.ReportSource -eq [NcsReportSource]::Scp) {
                        $interval = [Math]::Max($interval, 30)
                    }
                    $state.AutoRefreshTimer.Interval = [TimeSpan]::FromSeconds($interval)
                    $state.AutoRefreshTimer.Start()
                }

                $script:SchedulesLoaded = $false
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
                    Build-NcsTreeView -Controls $controls -TreeViewName "ActionLimitTree" -Groups $inventoryTree -TagProperty "limit" -Expanded $false -LeafIcon $script:IconFolder
                    Build-NcsTreeView -Controls $controls -TreeViewName "ScheduleLimitTree" -Groups $inventoryTree -TagProperty "limit" -Expanded $false -LeafIcon $script:IconFolder
                    $controls.ActionLimitEmptyText.Visibility = "Collapsed"
                    $controls.ScheduleLimitEmptyText.Visibility = "Collapsed"
                }
            } catch {
                Add-NcsConsoleLine -Controls $controls -Line "Inventory refresh failed: $($_.Exception.Message)"
            }
            try {
                $script:ActionGroups = Get-NcsRemotePlaybookTree -Settings $state.Settings
                $script:ActionItemMap = Get-NcsActionItemMap -Groups $script:ActionGroups
            } catch {
                $script:ActionGroups = @()
                $script:ActionItemMap = @{}
                Add-NcsConsoleLine -Controls $controls -Line "Playbook refresh failed: $($_.Exception.Message)"
            }
            Build-NcsTreeView -Controls $controls -TreeViewName "ActionTreeView" -Groups $script:ActionGroups -TagProperty "playbook" -Expanded $true -LeafIcon $script:IconFile
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

            $controls.ConsoleTextBox.Document.Blocks.Clear()
            $script:ConsoleLineCount = 0
            $controls.DetectedPathsListBox.ItemsSource = $null
            $controls.DetectedPathsPanel.Visibility = "Collapsed"
            $controls.ExitCodeTextBlock.Text = "-"
            $controls.DurationTextBlock.Text = "-"
            Set-NcsRunStateBadge -Controls $controls -State "Running"
            $selectedPlaybook = Get-NcsTreeViewSelection -Controls $controls -TreeViewName "ActionTreeView"
            if ([string]::IsNullOrWhiteSpace($selectedPlaybook)) {
                throw "Select an action before running."
            }

            # Confirm before running mutating actions
            $matchedAction = if ($script:ActionItemMap.ContainsKey($selectedPlaybook)) { $script:ActionItemMap[$selectedPlaybook] } else { $null }
            $isMutating = $null -ne $matchedAction -and $matchedAction.ContainsKey('mutating') -and $matchedAction['mutating'] -eq $true
            if ($isMutating) {
                $confirmBox = [System.Windows.Window]::new()
                $confirmBox.Title = ""
                $confirmBox.Width = 400
                $confirmBox.SizeToContent = "Height"
                $confirmBox.WindowStartupLocation = "CenterOwner"
                $confirmBox.Owner = $window
                $confirmBox.WindowStyle = "None"
                $confirmBox.ResizeMode = "NoResize"
                $confirmBox.Background = Get-NcsBrush -Color "#181b1f"
                $confirmBox.BorderBrush = Get-NcsBrush -Color "#f06478"
                $confirmBox.BorderThickness = [System.Windows.Thickness]::new(1)
                $csp = [System.Windows.Controls.StackPanel]::new()
                $csp.Margin = [System.Windows.Thickness]::new(16)
                $cTitle = [System.Windows.Controls.TextBlock]::new()
                $cTitle.Text = "Confirm Mutating Action"
                $cTitle.Foreground = Get-NcsBrush -Color "#f06478"
                $cTitle.FontSize = 14
                $cTitle.FontWeight = "Bold"
                $cTitle.Margin = [System.Windows.Thickness]::new(0,0,0,8)
                $csp.Children.Add($cTitle) | Out-Null
                $cLabel = [System.Windows.Controls.TextBlock]::new()
                $cLabel.Text = "This action makes changes to remote hosts.`n`nPlaybook: $selectedPlaybook`n`nType 'yes' to confirm:"
                $cLabel.Foreground = Get-NcsBrush -Color "#8e939c"
                $cLabel.Margin = [System.Windows.Thickness]::new(0,0,0,6)
                $cLabel.TextWrapping = "Wrap"
                $cLabel.FontSize = 11
                $csp.Children.Add($cLabel) | Out-Null
                $cInput = [System.Windows.Controls.TextBox]::new()
                $cInput.Background = Get-NcsBrush -Color "#1e2228"
                $cInput.Foreground = Get-NcsBrush -Color "#d8dce2"
                $cInput.BorderBrush = Get-NcsBrush -Color "#2c3038"
                $cInput.CaretBrush = Get-NcsBrush -Color "#d8dce2"
                $cInput.Padding = [System.Windows.Thickness]::new(8,5,8,5)
                $cInput.FontFamily = [System.Windows.Media.FontFamily]::new("Consolas")
                $csp.Children.Add($cInput) | Out-Null
                $cBtnPanel = [System.Windows.Controls.StackPanel]::new()
                $cBtnPanel.Orientation = "Horizontal"
                $cBtnPanel.HorizontalAlignment = "Right"
                $cBtnPanel.Margin = [System.Windows.Thickness]::new(0,10,0,0)
                $cOkBtn = [System.Windows.Controls.Button]::new()
                $cOkBtn.Content = "Run"
                $cOkBtn.Background = Get-NcsBrush -Color "#1e2228"
                $cOkBtn.Foreground = Get-NcsBrush -Color "#f06478"
                $cOkBtn.BorderBrush = Get-NcsBrush -Color "#f06478"
                $cOkBtn.Padding = [System.Windows.Thickness]::new(12,5,12,5)
                $cOkBtn.Margin = [System.Windows.Thickness]::new(6,0,0,0)
                $cOkBtn.IsDefault = $true
                $cOkBtn.Add_Click({ $confirmBox.DialogResult = $true })
                $cCancelBtn = [System.Windows.Controls.Button]::new()
                $cCancelBtn.Content = "Cancel"
                $cCancelBtn.Background = Get-NcsBrush -Color "#1e2228"
                $cCancelBtn.Foreground = Get-NcsBrush -Color "#8e939c"
                $cCancelBtn.BorderBrush = Get-NcsBrush -Color "#2c3038"
                $cCancelBtn.Padding = [System.Windows.Thickness]::new(12,5,12,5)
                $cCancelBtn.Add_Click({ $confirmBox.DialogResult = $false })
                $cBtnPanel.Children.Add($cCancelBtn) | Out-Null
                $cBtnPanel.Children.Add($cOkBtn) | Out-Null
                $csp.Children.Add($cBtnPanel) | Out-Null
                $confirmBox.Content = $csp
                $cInput.Focus() | Out-Null

                $confirmed = $confirmBox.ShowDialog()
                if ($confirmed -ne $true -or $cInput.Text.Trim().ToLower() -ne "yes") {
                    $controls.StatusTextBlock.Text = "Run cancelled — confirmation not provided."
                    return
                }
            }

            $controls.RunMetaText.Text = $selectedPlaybook
            $controls.StatusTextBlock.Text = "Starting remote command."
            Set-NcsRunningUiState -Controls $controls
            if ($controls.ConsolePane.Visibility -eq "Collapsed") {
                & $openConsole
            }

            $request = [NcsActionRequest]::new($selectedPlaybook)
            Set-NcsRequestFromControls -Controls $controls -Request $request
            $playCmd = Resolve-NcsPlaybookCommand -Settings $state.Settings -Request $request
            Add-NcsConsoleLine -Controls $controls -Line "> $playCmd"
            Sync-NcsConsoleScroll -Controls $controls
            $handle = Start-NcsRemoteCommand -Settings $state.Settings -Request $request `
                -OnOutput {
                    param($line)
                    Add-NcsConsoleLine -Controls $controls -Line $line
                } `
                -OnOutputBatch {
                    Sync-NcsConsoleScroll -Controls $controls
                    if ($controls.StatusTextBlock.Text -eq "Starting remote command.") {
                        $controls.StatusTextBlock.Text = "Running."
                    }
                } `
                -OnStale {
                    param($idleSeconds)
                    $msg = "[WARNING] No output for ${idleSeconds}s — task may be stuck. Use Stop to cancel."
                    Add-NcsConsoleLine -Controls $controls -Line $msg
                    $controls.StatusTextBlock.Text = "No output for ${idleSeconds}s — may be stuck"
                    Set-NcsRunStateBadge -Controls $controls -State "Blocked"
                } `
                -OnCompleted {
                    param($runResult)
                    $durationTimer.Stop()
                    $state.LastRunResult = $runResult
                    $state.CurrentHandle = $null
                    Set-NcsIdleUiState -Controls $controls
                    $badgeState = if ($runResult.WasCancelled) { "Canceled" } elseif ($runResult.Succeeded) { "Succeeded" } else { "Failed" }
                    Set-NcsRunStateBadge -Controls $controls -State $badgeState
                    Add-NcsConsoleLine -Controls $controls -Line "--- exit: $($runResult.ExitCode) | $($runResult.OutputLines.Length) lines | $(Format-NcsDuration -Duration $runResult.Duration) ---"
                    if (-not [string]::IsNullOrWhiteSpace($runResult.SessionLogPath)) {
                        Add-NcsConsoleLine -Controls $controls -Line "Session log: $($runResult.SessionLogPath)"
                    }
                    $controls.RunMetaText.Text = $runResult.Action
                    if ($runResult.WasCancelled) {
                        $controls.StatusTextBlock.Text = "Run cancelled."
                    } elseif ($runResult.Succeeded) {
                        $controls.StatusTextBlock.Text = "Run completed successfully."
                    } elseif (-not [string]::IsNullOrWhiteSpace($runResult.FailureStage)) {
                        $controls.StatusTextBlock.Text = "Run failed during $($runResult.FailureStage)."
                    } else {
                        $controls.StatusTextBlock.Text = "Run failed."
                    }
                    $controls.ExitCodeTextBlock.Text = [string] $runResult.ExitCode
                    $controls.DurationTextBlock.Text = Format-NcsDuration -Duration $runResult.Duration
                    $controls.DetectedPathsListBox.ItemsSource = $runResult.DetectedPaths
                    if ($null -ne $runResult.DetectedPaths -and @($runResult.DetectedPaths).Length -gt 0) {
                        $controls.DetectedPathsPanel.Visibility = "Visible"
                    }
                    Sync-NcsConsoleScroll -Controls $controls
                }
            $state.CurrentHandle = $handle
            $controls.CommandPreviewTextBox.Text = $playCmd
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
            $controls.StatusTextBlock.Text = "Cancellation requested. Waiting for remote process to stop."
        } catch {
            $controls.StatusTextBlock.Text = "Failed to cancel run: $($_.Exception.Message)"
        }
    })

    $getConsoleText = {
        $doc = $controls.ConsoleTextBox.Document
        $range = [System.Windows.Documents.TextRange]::new($doc.ContentStart, $doc.ContentEnd)
        return $range.Text
    }

    $controls.CopyOutputButton.Add_Click({
        try {
            $text = & $getConsoleText
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

    $getConsoleHtml = {
        $doc = $controls.ConsoleTextBox.Document
        $lines = [System.Collections.Generic.List[string]]::new()
        $lines.Add('<!DOCTYPE html><html><head><meta charset="utf-8"><style>body{background:#0d1015;color:#d8dce2;font-family:Consolas,monospace;font-size:13px;padding:16px;white-space:pre-wrap}span.ts{color:#555b66}span.stderr{color:#f47067}</style></head><body>')
        foreach ($block in $doc.Blocks) {
            if ($block -isnot [System.Windows.Documents.Paragraph]) { continue }
            $sb = [System.Text.StringBuilder]::new()
            foreach ($inline in $block.Inlines) {
                if ($inline -isnot [System.Windows.Documents.Run]) { continue }
                $escaped = [System.Net.WebUtility]::HtmlEncode($inline.Text)
                $fg = $inline.Foreground
                if ($null -ne $fg -and $fg -is [System.Windows.Media.SolidColorBrush]) {
                    $hex = "#{0:x2}{1:x2}{2:x2}" -f $fg.Color.R, $fg.Color.G, $fg.Color.B
                    [void] $sb.Append("<span style=`"color:$hex`">$escaped</span>")
                } else {
                    [void] $sb.Append($escaped)
                }
            }
            $lines.Add($sb.ToString())
        }
        $lines.Add('</body></html>')
        return $lines -join "`n"
    }

    $controls.ExportOutputButton.Add_Click({
        $dialog = [Microsoft.Win32.SaveFileDialog]::new()
        $dialog.Filter = "HTML files (*.html)|*.html|Text files (*.txt)|*.txt|Log files (*.log)|*.log|All files (*.*)|*.*"
        $actionTag = if ($state.LastRunResult) { $state.LastRunResult.Action } else { "output" }
        $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $dialog.FileName = "ncs-console-$actionTag-$timestamp.html"
        if ($dialog.ShowDialog()) {
            $path = $dialog.FileName
            if ($path -match '\.html?$') {
                Set-Content -LiteralPath $path -Value (& $getConsoleHtml) -Encoding UTF8
            } else {
                Set-Content -LiteralPath $path -Value (& $getConsoleText) -Encoding UTF8
            }
            $controls.StatusTextBlock.Text = "Output exported to $path."
        }
    })

    $window.Add_Closing({
        $durationTimer.Stop()
        if ($null -ne $state.AutoRefreshTimer) { $state.AutoRefreshTimer.Stop() }
        if ($state.CurrentHandle) {
            Stop-NcsRemoteCommand -Handle $state.CurrentHandle
            $state.CurrentHandle = $null
        }
        if ($null -ne $reportViewState.Control) {
            try { $reportViewState.Control.Dispose() } catch {
                $null = $_ # WebView2 disposal can throw during shutdown
            }
            $reportViewState.Control = $null
        }
        Stop-NcsTagFetches
        if ($null -ne $script:NcsWorkerPool) {
            try { $script:NcsWorkerPool.Close() } catch { }
            try { $script:NcsWorkerPool.Dispose() } catch { }
            $script:NcsWorkerPool = $null
        }
    })

    try {
        [void] $window.ShowDialog()
    } catch {
        $inner = $_.Exception
        while ($null -ne $inner.InnerException) { $inner = $inner.InnerException }
        Write-Host "NCS CONSOLE ERROR" -ForegroundColor Red
        Write-Host $inner.GetType().FullName -ForegroundColor Yellow
        Write-Host $inner.Message -ForegroundColor Yellow
        if ($inner.StackTrace) { Write-Host $inner.StackTrace -ForegroundColor DarkGray }
        if ($_.ScriptStackTrace) { Write-Host "`nPowerShell stack:`n$($_.ScriptStackTrace)" -ForegroundColor DarkGray }
        throw
    }
}
