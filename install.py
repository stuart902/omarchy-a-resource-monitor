#!/usr/bin/env python3
"""Install the optional plugin for the current desktop user, preserving settings."""
import copy
import json
import os
from pathlib import Path
import stat
import tempfile

PLUGIN_ID = 'tablet.resource-monitor'


def atomic_write(path, data, mode=0o644):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Refusing to replace a symlink: {}'.format(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
            os.fchmod(output.fileno(), mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def configured_layout(config):
    updated = copy.deepcopy(config)
    if not isinstance(updated, dict) or updated.get('version') != 1:
        raise ValueError('Expected shell config version 1; settings were not changed.')
    bar = updated.setdefault('bar', {})
    if not isinstance(bar, dict):
        raise ValueError('Invalid bar configuration; settings were not changed.')
    layout = bar.setdefault('layout', {})
    if not isinstance(layout, dict):
        raise ValueError('Invalid bar layout; settings were not changed.')
    right = layout.setdefault('right', [])
    if not isinstance(right, list):
        raise ValueError('Invalid right bar layout; settings were not changed.')
    # Keep an existing placement in ANY region rather than duplicate/move it.
    placed = any(isinstance(entries, list) and any(
        (entry == PLUGIN_ID or isinstance(entry, dict) and entry.get('id') == PLUGIN_ID)
        for entry in entries) for entries in layout.values())
    if not placed:
        right.append({'id': PLUGIN_ID})
    disabled = updated.get('disabledPlugins', [])
    if not isinstance(disabled, list):
        raise ValueError('Invalid disabledPlugins; settings were not changed.')
    if PLUGIN_ID in disabled:
        updated['disabledPlugins'] = [item for item in disabled if item != PLUGIN_ID]
    return updated


def desktop_quote(value):
    # Desktop Entry Exec has its own escaping rules, not shell quoting.
    value = str(value).replace('%', '%%')
    for character in ('\\', '"', '`', '$'):
        value = value.replace(character, '\\' + character)
    return '"' + value.replace('\\', '\\\\') + '"'


def application_directory(home, environment):
    # Match XDG discovery, including its empty/unset default. Relative XDG
    # paths are invalid and must be ignored rather than resolved against cwd.
    data_home = Path(environment.get('XDG_DATA_HOME') or home / '.local/share')
    if not data_home.is_absolute():
        data_home = home / '.local/share'
    return data_home / 'applications'


def install(source, home, defaults):
    desktop_path = application_directory(home, os.environ) / 'resource-monitor.desktop'
    config_path = home / '.config/omarchy-ipad/shell.json'
    if config_path.is_symlink():
        raise ValueError('Refusing to replace linked shell settings.')
    config_source = config_path if config_path.exists() else defaults
    if not config_source.is_file():
        raise ValueError('No existing shell configuration or Omarchy defaults found; nothing installed.')
    config_existed = config_path.exists()
    original = config_source.read_bytes()
    config = configured_layout(json.loads(original))
    config_mode = stat.S_IMODE(config_path.stat().st_mode) if config_path.exists() else 0o600
    # Validate all input before making changes. No root, sudo or session restart.
    monitor = (source / 'resource-monitor').read_bytes()
    widget = (source / 'BarWidget.qml').read_bytes()
    manifest = (source / 'manifest.json').read_bytes()
    license_text = (source / 'LICENSE').read_bytes()
    executable = home / '.local/bin/resource-monitor'
    launcher = home / '.local/bin/resource-monitor-launch'
    launcher_data = (source / 'resource-monitor-launch').read_bytes()
    desktop = ('[Desktop Entry]\nType=Application\nName=Resource Monitor\nGenericName=Task Manager\n'
               'Comment=View system resources and manage your processes\nExec=' + desktop_quote(launcher)
               + '\nIcon=utilities-system-monitor\nTerminal=false\nCategories=System;Monitor;\n'
               'Keywords=task;manager;process;cpu;memory;ram;resource;monitor;\n').encode()
    plugin = home / '.config/omarchy/plugins' / PLUGIN_ID
    files = (
        (executable, monitor, 0o755), (launcher, launcher_data, 0o755),
        (desktop_path, desktop, 0o644),
        (plugin / 'manifest.json', manifest, 0o644), (plugin / 'BarWidget.qml', widget, 0o644),
        (plugin / 'LICENSE', license_text, 0o644),
    )
    # Reject predictable destination conflicts before replacing any files.
    for path, _, _ in files:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError('Not a regular installation file: {}'.format(path))
        for parent in path.parents:
            if parent.exists() and not parent.is_dir():
                raise ValueError('Not an installation directory: {}'.format(parent))
    for path, data, mode in files:
        atomic_write(path, data, mode)
    # Detect external changes while staging files instead of overwriting them.
    if (config_path.is_symlink() or config_path.exists() != config_existed
            or (config_existed and config_path.read_bytes() != original)):
        raise ValueError('Shell settings changed during installation; rerun to add the bar button.')
    atomic_write(config_path, (json.dumps(config, indent=2) + '\n').encode(), config_mode)
    return desktop_path


def main():
    if os.geteuid() == 0:
        raise SystemExit('Run ./install.sh as the tablet desktop user, not root or sudo.')
    home = Path.home()
    source = Path(__file__).resolve().parent
    omarchy = Path(os.environ.get('OMARCHY_PATH', str(home / '.local/share/omarchy-ipad')))
    try:
        desktop_path = install(source, home, omarchy / 'config/omarchy/shell.json')
    except (OSError, ValueError) as error:
        raise SystemExit(str(error))
    print('Installed Resource Monitor launcher and bar layout.')
    print('Desktop entry: {}'.format(desktop_path))
    print('Apps visibility has not been checked. Open Omarchy menu > Apps to verify it.')
    print('If absent, sign out of the graphical session and back in to restart')
    print('Quickshell and refresh desktop entries. Save your work before signing out.')
    print('For tested manual restart steps over SSH, see README.md > Restart from SSH.')
    print('rescanPlugins/reloadConfig refresh the widget, not desktop-entry discovery.')
    print('For SSH installs, XDG_DATA_HOME must match the graphical session; see README.md.')


if __name__ == '__main__':
    main()
