# Resource Monitor for Omarchy A

A CPU and memory widget with a terminal task manager for **Omarchy A on iPad**.
Open it from **Omarchy menu → Apps → Resource Monitor** or the bar button.
Built for the iPad edition, `orchard/omarchy-a`. This is an optional plugin;
it is not included in the default OS image.

The bar shows CPU and RAM usage every two seconds. The task manager shows CPU,
memory, root disk usage, and a process list refreshed once per second. Repeated
launches focus the existing window. You can send SIGTERM to a selected process
after confirmation, using your normal user permissions.

## Requirements

Install as your desktop user (normally `tablet`), without `sudo`.

- Python 3.9 or later, Linux `/proc`, and procps `ps`.
- Omarchy A with Foot, Quickshell, Hyprland (`hyprctl`), and `omarchy-shell`.
- Git to clone this repository, or curl and tar to download an archive.

Process stopping requires Python's `pidfd_open` / `pidfd_send_signal` support and
a compatible kernel. If unavailable, the monitor still displays resources but
refuses to signal processes.

## Install or update

Run on the iPad, in a graphical terminal or over SSH:

```sh
git clone https://github.com/stuart902/omarchy-a-resource-monitor.git
cd omarchy-a-resource-monitor
./install.sh
```

For updates, run `git pull --ff-only` in your checkout, then `./install.sh` again.
If you do not use Git, download and extract the
[main branch archive](https://github.com/stuart902/omarchy-a-resource-monitor/archive/refs/heads/main.tar.gz)
and run `./install.sh` from the extracted directory.

The installer preserves unrelated shell settings and existing widget placement,
enables the widget, and writes these files:

| Location | Contents |
| --- | --- |
| `~/.local/bin/` | `resource-monitor` and `resource-monitor-launch` |
| `~/.config/omarchy/plugins/tablet.resource-monitor/` | Widget, manifest, and license |
| `~/.config/omarchy-ipad/shell.json` | Widget placement and enabled state |
| `${XDG_DATA_HOME:-$HOME/.local/share}/applications/` | `resource-monitor.desktop` |

An empty or relative `XDG_DATA_HOME` falls back to `~/.local/share`. When installing
over SSH, use the same absolute `XDG_DATA_HOME` as the graphical session.

Load the widget as your desktop user:

```sh
export OMARCHY_PATH="${OMARCHY_PATH:-$HOME/.local/share/omarchy-ipad}"
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
"$OMARCHY_PATH/bin/omarchy-shell" shell rescanPlugins
"$OMARCHY_PATH/bin/omarchy-shell" shell reloadConfig
```

Open **Omarchy menu → Apps → Resource Monitor**. If the entry is missing, save
work and sign out of the graphical session and back in. Plugin reloads do not
refresh Quickshell's desktop-entry registry. For an SSH-only restart, follow the
[restart procedure](docs/troubleshooting.md#restart-from-ssh).

## Controls

| Control | Action |
| --- | --- |
| Bar button or Apps entry | Open or focus the task manager; enable the widget |
| Up/Down, j/k, mouse wheel, or on-screen buttons | Move through processes |
| Tap or click a process | Select it |
| K or **Stop [K]** | Request SIGTERM for the selected process |
| y or **Confirm** | Confirm the request |
| n, Escape, or **Cancel** during confirmation | Cancel the request |
| Escape or window close | Close the task manager; leave the widget running |
| q or **Quit** | Close the task manager and disable the widget |

Process CPU is a lifetime average, as reported by `ps`, rather than usage over the
last refresh interval. Process identity is checked before signaling; PID 1 and
the monitor itself are protected. Touch controls require Foot mouse reporting.
The minimum task-manager size is 42 columns by 10 rows.

To disable the widget while leaving the task manager alone, use the environment
exports above, then:

```sh
"$OMARCHY_PATH/bin/omarchy-shell" shell setPluginEnabled tablet.resource-monitor false
```

Launching Resource Monitor enables it again. From a graphical terminal, you can
also run `~/.local/bin/resource-monitor-launch`. For a one-shot CPU/RAM reading,
run `~/.local/bin/resource-monitor --stats`; `--help` lists command-line options.

## Maintenance

- [Troubleshooting and SSH restart](docs/troubleshooting.md)
- [Uninstall](docs/uninstall.md)
- [Development and device checks](docs/development.md)

Licensed under [MIT](LICENSE).
