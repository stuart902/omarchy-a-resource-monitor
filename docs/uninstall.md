# Uninstall

Run these steps as the desktop user on the iPad. Do not delete the shared
applications directory, shell config or other plugins.

1. In Resource Monitor, press **q** or tap **Quit** to stop its window and widget.
   If the window is already closed, disable the widget using the README's
   `setPluginEnabled tablet.resource-monitor false` command.
2. Back up `~/.config/omarchy-ipad/shell.json`. With a JSON-aware editor, remove
   only `tablet.resource-monitor` entries from `bar.layout` (a string entry or
   an object whose `id` has that value) and `disabledPlugins`. Preserve all other
   layout entries, settings and the file's permissions. Save valid JSON, then
   use `omarchy-shell shell reloadConfig` as in the README. Avoid concurrent
   settings changes while editing.
3. Remove these installed files only:

   - `~/.local/bin/resource-monitor`
   - `~/.local/bin/resource-monitor-launch`
   - `resource-monitor.desktop` from the applications directory printed during
     installation (`~/.local/share/applications` by default, or the custom
     `XDG_DATA_HOME/applications` used at install time)
   - `manifest.json`, `BarWidget.qml` and `LICENSE` inside
     `~/.config/omarchy/plugins/tablet.resource-monitor/`

   Remove the plugin directory only if it is now empty. If a listed file has
   been replaced with something unrelated, inspect it before removing it.
4. Run `omarchy-shell shell rescanPlugins`. If Apps still shows a stale entry,
   save work and sign out/in, or use the documented
   [Quickshell restart](troubleshooting.md#restart-from-ssh).

The per-session lock file in `XDG_RUNTIME_DIR` can remain until session cleanup;
it is harmless when unlocked. Do not remove it while a launcher is running.
Downloaded source archives/checkouts are separate from the installed application
and can be removed when you no longer need them.

[Back to README](../README.md)
