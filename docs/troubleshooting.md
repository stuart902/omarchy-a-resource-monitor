# Apps discovery and SSH troubleshooting

Apps discovery is independent of the CPU/RAM widget. The bar launches an absolute
path; Apps uses Quickshell's desktop-entry registry. A working bar button does not
prove the Apps entry was discovered.

## Check the installation

The installer prints the desktop-entry path:
`${XDG_DATA_HOME:-$HOME/.local/share}/applications/resource-monitor.desktop`.
Unset, empty or relative `XDG_DATA_HOME` uses `~/.local/share`. The launcher is
`~/.local/bin/resource-monitor-launch` and must be executable. If available, run
`desktop-file-validate` on the printed desktop-entry path.

SSH and Quickshell must use the same absolute `XDG_DATA_HOME`. Setting
`XDG_RUNTIME_DIR` only enables IPC; it does not align application search paths.
If the graphical session uses a custom data home, export that value before
installing from SSH. Restarting with mismatched paths will not fix discovery.

The desktop ID is `resource-monitor`, distinct from plugin ID
`tablet.resource-monitor`. Check for conflicting entries or Hidden/NoDisplay
flags in the user applications directory and `XDG_DATA_DIRS`, and for configured
launcher hides. Preserve unrelated applications and settings. An older build is
not proof of a conflicting file.

## Refresh Apps

`rescanPlugins` and `reloadConfig` refresh plugins/settings, not the process-wide
desktop-entry registry. If Apps is missing the entry, save work and sign out of
the graphical session and back in, or use the SSH procedure below. No reboot is
required. `update-desktop-database` updates MIME associations, not this registry.

## Restart from SSH

Run as your desktop user on the iPad. If you installed Omarchy A in a custom
location, export `OMARCHY_PATH` first. This captures the running shell's environment before
stopping it, so the replacement retains the graphical display and XDG settings
that may be absent from SSH. It targets the Omarchy shell configuration only and
stops without changing anything if it cannot identify exactly one instance.

```sh
python3 - <<'PY'
import os
import re
import subprocess
from pathlib import Path

omarchy = Path(os.environ.get('OMARCHY_PATH') or Path.home() / '.local/share/omarchy-ipad')
config = str(omarchy / 'shell/shell.qml')
result = subprocess.run(
    ['pgrep', '-u', str(os.getuid()), '-f', '^qs -p ' + re.escape(config) + '$'],
    text=True, stdout=subprocess.PIPE
)
pids = result.stdout.split()
if len(pids) != 1:
    raise SystemExit('Expected one Omarchy shell; found: ' + str(pids))

pid = pids[0]
raw = Path('/proc', pid, 'environ').read_bytes()
environment = dict(
    item.decode().split('=', 1)
    for item in raw.split(b'\0') if b'=' in item
)
print('Restarting Quickshell PID', pid, flush=True)
subprocess.run(['qs', 'kill', '-p', config], env=environment, check=True)
subprocess.run(['qs', '-d', '-p', config], env=environment, check=True)
subprocess.run(['qs', 'list', '-p', config], env=environment, check=True)
PY
```

Wait for the bar to return and confirm the process listing shows a different
PID. Disable the widget using the [README command](../README.md#use), then check
Apps and select Resource Monitor; launching should enable the widget again.
A reconnect to SSH alone does not restart Quickshell.

## If discovery still fails

Record the Quickshell version, desktop-entry path and contents, whether its
applications directory existed before installation, and relevant environment
values in both the installing terminal and running Quickshell process:
`HOME`, `XDG_DATA_HOME`, `XDG_DATA_DIRS`, `XDG_CURRENT_DESKTOP`,
`XDG_SESSION_DESKTOP`, `DESKTOP_SESSION`, `XDG_RUNTIME_DIR`, `WAYLAND_DISPLAY`
and `PATH`. Do not dump the entire environment, which may contain secrets.

Check the installed shell's `default/omarchy/launcher.hides` and
`shell/services/hidden-entries.sh`. Compare conflicting desktop IDs across user
and system application directories without deleting them. Record visibility
before and after a full process restart, then test launch from Apps with the
widget disabled. Do not delete the real applications directory to simulate a
first install.

[Back to README](../README.md)
