"""Installer/discovery regression tests, independent of the bar widget.

Native discovery runs when qs is installed. Set OMARCHY_SHELL_DIR to the shell
directory containing services/AppSearch.js to test the real Apps search filter.
"""
import configparser
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_resource_monitor import installer, SOURCE


class AppsDiscoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / 'tablet home'
        self.home.mkdir()
        self.defaults = self.root / 'defaults.json'
        self.defaults.write_text(json.dumps({'version': 1, 'bar': {'layout': {'right': []}}}))
        self.environment = {**os.environ, 'HOME': str(self.home), 'XDG_DATA_HOME': ''}
        environment = patch.dict(os.environ, self.environment, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def install(self):
        self.desktop = installer.install(SOURCE, self.home, self.defaults)
        parsed = configparser.ConfigParser(interpolation=None)
        parsed.read(self.desktop)
        self.entry = parsed['Desktop Entry']
        return self.desktop

    def test_xdg_default_empty_unset_and_relative(self):
        expected = self.home / '.local/share/applications'
        for environment in ({}, {'XDG_DATA_HOME': ''}, {'XDG_DATA_HOME': 'relative/data'}):
            with self.subTest(environment=environment):
                self.assertEqual(installer.application_directory(self.home, environment), expected)

    def test_custom_data_home_installs_in_discovery_path_and_preserves_other_apps(self):
        data_home = self.root / 'session data'
        os.environ['XDG_DATA_HOME'] = str(data_home)
        other = data_home / 'applications/other.desktop'
        other.parent.mkdir(parents=True)
        other.write_text('[Desktop Entry]\nType=Application\nName=Other\nExec=/bin/true\n')
        original = other.read_bytes()
        self.assertEqual(self.install(), data_home / 'applications/resource-monitor.desktop')
        self.assertFalse((self.home / '.local/share/applications').exists())
        self.install()
        self.assertEqual(other.read_bytes(), original)

    def test_desktop_id_permissions_and_visibility_flags(self):
        self.assertFalse((self.home / '.local/share/applications').exists())
        self.install()
        self.assertEqual(self.desktop.stem, 'resource-monitor')
        self.assertEqual(self.entry['Type'], 'Application')
        self.assertEqual(self.entry['Name'], 'Resource Monitor')
        self.assertEqual(self.entry['Terminal'], 'false')
        self.assertEqual(self.entry['Exec'], installer.desktop_quote(self.home / '.local/bin/resource-monitor-launch'))
        self.assertTrue(self.entry['Categories'].endswith(';'))
        self.assertTrue(self.entry['Keywords'].endswith(';'))
        for key in ('Hidden', 'NoDisplay', 'OnlyShowIn', 'NotShowIn', 'TryExec'):
            self.assertNotIn(key, self.entry)
        self.assertEqual(stat.S_IMODE(self.desktop.stat().st_mode), 0o644)
        for executable in ('resource-monitor', 'resource-monitor-launch'):
            self.assertEqual(stat.S_IMODE((self.home / '.local/bin' / executable).stat().st_mode), 0o755)

    def test_installer_does_not_claim_apps_visibility_or_restart_desktop(self):
        os.environ['OMARCHY_PATH'] = str(self.root / 'omarchy')
        defaults = Path(os.environ['OMARCHY_PATH']) / 'config/omarchy/shell.json'
        defaults.parent.mkdir(parents=True)
        defaults.write_bytes(self.defaults.read_bytes())
        with patch.object(installer.os, 'geteuid', return_value=1000), \
             patch.object(installer.Path, 'home', return_value=self.home), \
             patch('builtins.print') as output:
            installer.main()
        message = '\n'.join(str(call.args[0]) for call in output.call_args_list)
        self.assertIn(str(self.home / '.local/share/applications/resource-monitor.desktop'), message)
        self.assertIn('visibility has not been checked', message)
        self.assertNotIn('Update > Process > Shell', message)
        self.assertIn('sign out of the graphical session', message)
        self.assertIn('Save your work before signing out', message)
        self.assertIn('README.md > Restart from SSH', message)
        self.assertIn('XDG_DATA_HOME must match', message)

    @unittest.skipUnless(shutil.which('desktop-file-validate'), 'desktop-file-validate not installed')
    def test_desktop_entry_validates(self):
        self.install()
        subprocess.run(['desktop-file-validate', str(self.desktop)], check=True, capture_output=True, text=True)

    def test_real_apps_search_filter_includes_installed_entry_without_widget(self):
        shell_dir = os.environ.get('OMARCHY_SHELL_DIR')
        node = shutil.which('node')
        if not shell_dir or not node:
            self.skipTest('requires node and OMARCHY_SHELL_DIR for the real Apps filter')
        self.install()
        entry = {'id': self.desktop.stem, 'name': self.entry['Name'],
                 'genericName': self.entry['GenericName'], 'comment': self.entry['Comment'],
                 'keywords': self.entry['Keywords'].strip(';').split(';'), 'noDisplay': False}
        # Use the actual shell search implementation, not a copied approximation.
        script = '''
const assert = require('node:assert/strict');
const search = require(process.argv[1]);
const entry = JSON.parse(process.argv[2]);
for (const query of ['', 'Resource Monitor', 'cpu', 'task manager']) {
    assert.deepEqual(search.sortedEntries([entry], query, () => false).map(row => row.entry.id), ['resource-monitor']);
}
assert.equal(search.sortedEntries([entry], '', () => true).length, 0);
assert.equal(search.sortedEntries([{...entry, noDisplay: true}], '', () => false).length, 0);
'''
        subprocess.run([node, '-e', script, str(Path(shell_dir).resolve() / 'services/AppSearch.js'),
                        json.dumps(entry)], check=True, capture_output=True, text=True)

    @unittest.skipUnless(shutil.which('qs'), 'Quickshell not installed; run on the device')
    def test_fresh_native_registry_discovers_and_executes_without_bar(self):
        os.environ['XDG_DATA_HOME'] = str(self.root / 'session data')
        os.environ['XDG_DATA_DIRS'] = str(self.root / 'system data')
        self.install()
        # Disable the widget on disk and load a standalone native registry.
        config_path = self.home / '.config/omarchy-ipad/shell.json'
        config = json.loads(config_path.read_text())
        config['disabledPlugins'] = [installer.PLUGIN_ID]
        config_path.write_text(json.dumps(config))
        desktop_before = self.desktop.read_bytes()
        marker = self.root / 'launched-from-desktop'
        launcher = self.home / '.local/bin/resource-monitor-launch'
        launcher.write_text('#!/bin/sh\nprintf launched > "$APPS_LAUNCH_MARKER"\n')
        probe = self.root / 'probe.qml'
        probe.write_bytes((SOURCE / 'tests/desktop_entries.qml').read_bytes())
        result = subprocess.run(['qs', '-p', str(probe)], env={**os.environ,
            'QT_QPA_PLATFORM': 'offscreen', 'APPS_PROBE_EXECUTE': '1',
            'APPS_LAUNCH_MARKER': str(marker)}, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        match = re.search(r'APPS_PROBE=(\{[^\n]*\})', result.stdout + result.stderr)
        self.assertIsNotNone(match, result.stdout + result.stderr)
        report = json.loads(match.group(1))
        self.assertTrue(report['found'])
        self.assertTrue(report['visible'])
        self.assertEqual(report['command'], [str(launcher)])
        self.assertEqual(marker.read_text(), 'launched')
        self.assertEqual(self.desktop.read_bytes(), desktop_before)
        self.assertEqual(json.loads(config_path.read_text())['disabledPlugins'], [installer.PLUGIN_ID])


if __name__ == '__main__':
    unittest.main()
