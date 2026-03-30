# ncs-ui

`ncs-ui` is a Windows PowerShell + WPF operator console for running common `ansible-ncs` workflows on a remote Linux host over SSH.

## What It Does

V1 focuses on execution, not editing or reporting. The app can:

- run the main `ansible-ncs` workflows
- limit runs to a site or a specific Ansible host when the selected action supports it
- stream stdout/stderr into a live console pane
- validate SSH/repo/vault prerequisites before allowing a run
- persist operator settings locally

The backend target is the sibling repo at `../dev/ansible-ncs`, but the app stores a configurable remote repo path so the operator can point at any checked-out instance.

## Structure

- `ncs-ui.ps1` - application entrypoint
- `App/MainWindow.xaml` - WPF layout
- `Modules/NcsUi.Types.psm1` - internal typed contracts
- `Modules/NcsUi.Settings.psm1` - settings load/save/defaults
- `Modules/NcsUi.Execution.psm1` - remote SSH execution and action wrappers
- `Modules/NcsUi.Preflight.psm1` - local and remote readiness checks
- `Modules/NcsUi.Wpf.psm1` - WPF startup and event wiring

## Requirements

- Windows with PowerShell and WPF support
- `ssh.exe` available on the Windows host
- network access to the remote Linux execution host
- remote host has the `ansible-ncs` repo checked out and configured
- remote repo has inventory and vault files present

## Launch

```powershell
pwsh -File .\ncs-ui.ps1
```

If execution policy blocks unsigned scripts, set `RemoteSigned` for the current user:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

## Default Action Mapping

- `Run All` -> `make run`
- `Run Site` -> `make run-site SITE=<site>`
- `Run Host` -> `ansible-playbook ... --limit <host>,localhost`
- `Run vCenter` -> `make run-vcenter`
- `Dry Run` -> `make dry-run`
- `Debug` -> `make debug`
- `Inventory Preview` -> `make inventory`
- `Inventory Host` -> `make inventory-host HOST=<host>`
- `Recent Logs` -> `make logs-recent`

If the configured vault path is not the default `.vaultpass`, the wrapper falls back to direct `ansible-playbook` commands for the actions that require a vault file, so the UI still honors the configured remote path without mutating the backend repo.

## Settings Storage

Settings are stored per-user under:

```text
%APPDATA%\NcsUi\settings.json
```

Stored values include:

- SSH host, port, username, and auth mode
- SSH key path or password depending on the selected auth mode
- remote repo path
- remote vault path
- default site
- default Ansible host
- last selected action

The app stores the remote vault file path. If `Password` SSH mode is selected, the SSH password is encrypted at rest using Windows DPAPI (tied to the current user account). Legacy plaintext passwords from older settings files are migrated automatically on the next save. The settings file should still be treated as sensitive.

## Enterprise Deployment Notes

The app uses standard Windows components but some patterns may trigger EDR/AV heuristics. To whitelist in managed environments:

- **Process chain**: `pwsh.exe` spawns `ssh.exe` with redirected streams for live console output. This is expected.
- **WPF assemblies**: The app loads `PresentationFramework`, `PresentationCore`, and `WindowsBase` for the GUI. This is standard WPF usage.
- **SSH_ASKPASS**: When using Password auth mode, SSH_ASKPASS points to a bundled `Scripts/askpass.cmd` that reads a password from a process environment variable. No credentials are written to disk. Agent or KeyFile auth modes avoid this entirely and are recommended for enterprise use.
- **DPAPI credential storage**: `ConvertTo-SecureString`/`ConvertFrom-SecureString` are used to encrypt the SSH password at rest in `%APPDATA%\NcsUi\settings.json`. This is standard Windows credential protection.
- **Execution policy**: The app does not require `-ExecutionPolicy Bypass`. Use `RemoteSigned` with code-signed scripts for managed deployments.
