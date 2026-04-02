# ncs-console

`ncs-console` is a Windows PowerShell + WPF operator console for running common `ansible-ncs` workflows on a remote Linux host over SSH.

## What It Does

V1 focuses on execution, not editing or reporting. The app can:

- run the main `ansible-ncs` workflows
- limit runs to a site or a specific Ansible host when the selected action supports it
- stream stdout/stderr into a live console pane
- sync and display generated HTML reports in the reports pane
- validate SSH/repo/vault prerequisites before allowing a run
- persist operator settings locally

The backend target is the sibling repo at `../dev/ansible-ncs`, but the app stores a configurable remote repo path so the operator can point at any checked-out instance.

## Structure

- `ncs-console.ps1` - application entrypoint
- `App/MainWindow.xaml` - WPF layout
- `Modules/NcsConsole.Types.ps1` - internal typed contracts
- `Modules/NcsConsole.Settings.ps1` - settings load/save/defaults
- `Modules/NcsConsole.Execution.ps1` - remote SSH execution and action wrappers
- `Modules/NcsConsole.Preflight.ps1` - local and remote readiness checks
- `Modules/NcsConsole.Wpf.ps1` - WPF startup and event wiring

## Requirements

- Windows with PowerShell and WPF support
- `ssh.exe` available on the Windows host
- Microsoft Edge WebView2 Runtime available on the Windows host for inline report viewing
- network access to the remote Linux execution host
- remote host has the `ansible-ncs` repo checked out and configured
- remote repo has inventory and vault files present

## Launch

```powershell
pwsh -File .\ncs-console.ps1
```

If execution policy blocks unsigned scripts, set `RemoteSigned` for the current user:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

## Actions

Actions are auto-discovered from the `playbooks/` directory on the remote host. The tree hierarchy mirrors the directory structure. Labels, options, and mutating flags are extracted from playbook YAML and `# >>> / # <<<` metadata blocks. The app runs `ansible-playbook` directly (activating `.venv` if present) — no Makefile, Justfile, or make targets are involved.

## Settings Storage

Settings are stored per-user under:

```text
%APPDATA%\NcsConsole\settings.json
```

Stored values include:

- SSH host, port, username, and auth mode
- SSH key path (if KeyFile auth mode is selected)
- remote repo path
- remote vault path
- last selected action

Passwords are never stored to disk. If `Password` SSH mode is selected, the password must be re-entered each session.

## Reports

The reports pane mirrors `/srv/samba/reports` from the remote host into a local cache and loads the HTML reports inline with WebView2. The repo ships the required WebView2 app assemblies under `App/lib/WebView2`; if the machine runtime is unavailable, the app falls back to opening the report in the default browser.

## Enterprise Deployment Notes

The app uses standard Windows components but some patterns may trigger EDR/AV heuristics. To whitelist in managed environments:

- **Process chain**: `pwsh.exe` spawns `ssh.exe` with redirected streams for live console output. This is expected.
- **WPF assemblies**: The app loads `PresentationFramework`, `PresentationCore`, and `WindowsBase` for the GUI. This is standard WPF usage.
- **SSH_ASKPASS**: When using Password auth mode, SSH_ASKPASS points to a bundled `Scripts/askpass.cmd` that reads a password from a process environment variable. No credentials are written to disk. Agent or KeyFile auth modes avoid this entirely and are recommended for enterprise use.
- **No credential storage**: Passwords are never persisted. They live in memory only for the duration of the session.
- **Execution policy**: The app does not require `-ExecutionPolicy Bypass`. Use `RemoteSigned` with code-signed scripts for managed deployments.
