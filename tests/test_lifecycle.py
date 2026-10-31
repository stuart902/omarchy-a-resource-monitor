"""Exercise the installed launcher with real locks/processes and fake desktop tools."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, Mock

from test_resource_monitor import load, monitor, installer, SOURCE

launcher = load('resource_monitor_launch', SOURCE / 'resource-monitor-launch')


class LauncherTests(unittest.TestCase):
    def test_enable_and_disable_target_only_our_plugin_and_report_failure(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                with patch.object(launcher.subprocess, 'run', return_value=Mock(stdout='ok\n')) as run:
                    launcher.set_widget_enabled(enabled)
                self.assertEqual(run.call_args.args[0], [
                    'omarchy-shell', 'shell', 'setPluginEnabled', 'tablet.resource-monitor',
                    'true' if enabled else 'false'])
                with patch.object(launcher.subprocess, 'run', return_value=Mock(stdout='unknown')):
                    with self.assertRaises(RuntimeError):
                        launcher.set_widget_enabled(enabled)

    def test_focus_requires_terminal_pid_and_exact_app_id(self):
        clients = [{'pid': 123, 'class': 'other', 'address': '0x1'},
                   {'pid': 456, 'class': launcher.APP_ID, 'address': '0x2'},
                   {'pid': 123, 'class': launcher.APP_ID, 'address': '0x3'}]
        with patch.object(launcher.subprocess, 'check_output', return_value=json.dumps(clients)), \
             patch.object(launcher.subprocess, 'run') as run:
            self.assertTrue(launcher.focus_window(123))
        self.assertEqual(run.call_args.args[0], ['hyprctl', 'dispatch', 'focuswindow', 'address:0x3'])

    def test_stats_is_a_single_helper_and_unload_terminates_it(self):
        widget = (SOURCE / 'BarWidget.qml').read_text()
        self.assertIn('"/.local/bin/resource-monitor", "--stats"', widget)
        self.assertIn('if (stats && stats.running) stats.running = false', widget)
        self.assertNotIn('["sh",', widget)
        with patch.object(monitor, 'read_cpu', side_effect=[(0, (10, 5)), (12.4, (20, 7))]), \
             patch.object(monitor, 'read_memory', return_value=(3, 4)), \
             patch.object(monitor.time, 'sleep'), patch('builtins.print') as output:
            monitor.print_stats()
        output.assert_called_once_with('12 75')

    def test_quit_button_and_keyboard_actions_request_full_quit(self):
        for key in (ord('q'), monitor.curses.KEY_MOUSE):
            with self.subTest(key=key):
                screen = Mock()
                screen.getmaxyx.return_value = (20, 70)
                screen.getch.side_effect = [-1, key]
                with patch.object(monitor, 'read_cpu', return_value=(1, (1, 1))), \
                     patch.object(monitor, 'read_memory', return_value=(1, 2)), \
                     patch.object(monitor, 'processes', return_value=[]), \
                     patch.object(monitor.curses, 'curs_set'), \
                     patch.object(monitor.curses, 'mousemask'), \
                     patch.object(monitor.curses, 'mouseinterval'), \
                     patch.object(monitor, 'request_quit') as quit_request, \
                     patch.object(monitor.curses, 'getmouse', return_value=(
                         0, 34, 18, 0, monitor.curses.BUTTON1_RELEASED)):
                    monitor.main(screen)
                self.assertEqual(screen.getch.call_count, 2)
                quit_request.assert_called_once_with()

    def test_quit_marker_is_written_only_to_current_launch_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'quit'
            with patch.dict(os.environ, RESOURCE_MONITOR_QUIT_FILE=str(path)):
                monitor.request_quit()
            self.assertEqual(path.read_text(), 'quit\n')

    def test_terminal_start_failure_releases_state_and_retains_widget(self):
        with tempfile.TemporaryDirectory() as directory:
            with (Path(directory) / 'lock').open('w+') as lease:
                lease.write('123')
                with patch.object(launcher.subprocess, 'Popen', side_effect=FileNotFoundError), \
                     patch.object(launcher, 'set_widget_enabled') as enabled:
                    with self.assertRaises(FileNotFoundError):
                        launcher.supervise(lease)
                enabled.assert_called_once_with(True)
                lease.seek(0)
                self.assertEqual(lease.read(), '')

    def test_enable_failure_does_not_start_a_window(self):
        with tempfile.TemporaryDirectory() as directory:
            with (Path(directory) / 'lock').open('w+') as lease:
                with patch.object(launcher, 'set_widget_enabled', side_effect=RuntimeError('unavailable')), \
                     patch.object(launcher.subprocess, 'Popen') as terminal:
                    with self.assertRaises(RuntimeError):
                        launcher.supervise(lease)
                terminal.assert_not_called()

    def test_lock_timeout_does_not_start_a_second_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lock'
            with path.open('w+') as owner, path.open('r+') as contender:
                launcher.fcntl.flock(owner, launcher.fcntl.LOCK_EX)
                owner.write('123')
                owner.flush()
                with patch.object(launcher, 'focus_window', return_value=False):
                    with self.assertRaises(RuntimeError):
                        launcher.acquire_or_focus(contender, timeout=0)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.home = self.root / 'home with spaces'
        self.home.mkdir()
        defaults = self.root / 'defaults'
        defaults.write_text('{"version":1}')
        installer.install(SOURCE, self.home, defaults)
        self.bin = self.home / '.local/bin'
        self.env = dict(os.environ, HOME=str(self.home), XDG_RUNTIME_DIR=str(self.root),
                        HYPRLAND_INSTANCE_SIGNATURE='lifecycle-test', TEST_ROOT=str(self.root),
                        PATH=str(self.bin) + os.pathsep + os.environ['PATH'])
        self.children = []
        self.addCleanup(self.stop_children)
        # A fake task manager still runs as a separate child of Foot, so tests
        # check both processes disappear on quit, crash, and window close.
        self.tool('fake-manager', '''
import runpy, time
while not (root / 'exit').exists():
    time.sleep(.01)
reason = (root / 'exit').read_text()
code = 0 if reason == 'escape' else int(reason)
if reason == '0':
    # Use the installed manager's real quit protocol, not a fake marker writer.
    runpy.run_path(str(Path(__file__).with_name('resource-monitor')))['request_quit']()
sys.exit(code)
''')
        self.tool('foot', '''
import signal, subprocess, time
with (root / 'starts').open('a') as out:
    out.write(str(os.getpid()) + '\\n')
child = subprocess.Popen([str(Path(__file__).with_name('fake-manager'))])
(root / 'manager').write_text(str(child.pid))
def close(signum, frame):
    child.terminate()
signal.signal(signal.SIGTERM, close)
# Deliberately delay mapping to exercise simultaneous startup requests.
time.sleep(.2)
(root / 'window').write_text(str(os.getpid()))
try:
    code = child.wait()
finally:
    (root / 'window').unlink(missing_ok=True)
sys.exit(code)
''')
        self.tool('hyprctl', '''
if sys.argv[1:] == ['-j', 'clients']:
    pid = int((root / 'window').read_text()) if (root / 'window').exists() else 0
    print(json.dumps([{'pid': pid, 'class': 'tablet-resource-monitor', 'address': '0xabc'}]))
else:
    assert sys.argv[1:] == ['dispatch', 'focuswindow', 'address:0xabc']
    with (root / 'focuses').open('a') as out:
        out.write('focus\\n')
''')
        self.tool('omarchy-shell', '''
import time
assert sys.argv[1:4] == ['shell', 'setPluginEnabled', 'tablet.resource-monitor']
assert sys.argv[4] in ('true', 'false')
enabled = sys.argv[4] == 'true'
if not enabled:
    (root / 'cleanup-started').touch()
    while (root / 'hold-cleanup').exists():
        time.sleep(.01)
with (root / ('enabled' if enabled else 'disabled')).open('a') as out:
    out.write(sys.argv[4] + '\\n')
(root / 'widget-state').write_text(sys.argv[4])
print('ok')
''')
        (self.root / 'widget-state').write_text('false')

    def tool(self, name, body):
        path = self.bin / name
        path.write_text('#!' + sys.executable + '\nimport os, sys, json\nfrom pathlib import Path\n'
                        'root = Path(os.environ["TEST_ROOT"])\n' + body)
        path.chmod(0o755)

    def start(self):
        child = subprocess.Popen([sys.executable, str(self.bin / 'resource-monitor-launch')],
                                 env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.children.append(child)
        return child

    def stop_children(self):
        for child in self.children:
            if child.poll() is None:
                child.terminate()
            child.communicate(timeout=8)

    def wait_for(self, predicate):
        deadline = time.monotonic() + 8
        while not predicate():
            if time.monotonic() > deadline:
                self.fail('Timed out waiting for lifecycle transition')
            time.sleep(.01)

    def wait_window(self):
        self.wait_for(lambda: (self.root / 'window').exists())
        return int((self.root / 'window').read_text())

    def finished(self, child, expected=0, disabled=True):
        stdout, stderr = child.communicate(timeout=8)
        self.assertEqual(child.returncode, expected, stderr.decode())
        self.assertEqual((self.root / 'widget-state').read_text(), 'false' if disabled else 'true')
        self.assertFalse((self.root / 'window').exists())
        pid = int((self.root / 'manager').read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_concurrent_and_repeated_launches_focus_then_quit_and_relaunch(self):
        owner = self.start()
        # Keep all requests alive together while Foot is still mapping.
        for _ in range(6):
            self.start()
        self.wait_for(lambda: sum(child.poll() is None for child in self.children) == 1)
        for child in self.children:
            if child.poll() is not None:
                self.assertEqual(child.returncode, 0, child.communicate()[1].decode())
        # Owner started first, but scheduling can let another request win.
        live = [child for child in self.children if child.poll() is None]
        self.assertEqual(len(live), 1)
        owner = live[0]
        self.assertEqual(len((self.root / 'starts').read_text().splitlines()), 1)
        self.assertEqual((self.root / 'widget-state').read_text(), 'true')
        again = self.start()
        self.assertEqual(again.wait(timeout=8), 0)
        self.assertEqual(len((self.root / 'focuses').read_text().splitlines()), 7)
        self.assertEqual(len((self.root / 'starts').read_text().splitlines()), 1)
        (self.root / 'exit').write_text('0')
        self.finished(owner)
        (self.root / 'exit').unlink()
        relaunched = self.start()
        self.wait_window()
        self.assertEqual(len((self.root / 'starts').read_text().splitlines()), 2)
        (self.root / 'exit').write_text('0')
        self.finished(relaunched)

    def test_window_close_and_crash_retain_bar_and_allow_reopening(self):
        for mode in ('window-close', 'crash'):
            with self.subTest(mode=mode):
                owner = self.start()
                pid = self.wait_window()
                if mode == 'window-close':
                    os.kill(pid, signal.SIGTERM)
                    expected = 256 - signal.SIGTERM
                else:
                    os.kill(int((self.root / 'manager').read_text()), signal.SIGKILL)
                    expected = 256 - signal.SIGKILL
                self.finished(owner, expected, disabled=False)
        self.assertFalse((self.root / 'disabled').exists())
        owner = self.start()
        self.wait_window()
        (self.root / 'exit').write_text('0')
        self.finished(owner)
        self.assertEqual(len((self.root / 'starts').read_text().splitlines()), 3)
        self.assertEqual(len((self.root / 'disabled').read_text().splitlines()), 1)

    def test_existing_window_launch_reenables_manually_disabled_bar(self):
        owner = self.start()
        self.wait_window()
        (self.root / 'widget-state').write_text('false')
        again = self.start()
        self.assertEqual(again.wait(timeout=8), 0)
        self.assertEqual((self.root / 'widget-state').read_text(), 'true')
        self.assertEqual(len((self.root / 'starts').read_text().splitlines()), 1)
        (self.root / 'exit').write_text('0')
        self.finished(owner)

    def test_escape_exit_zero_retains_widget(self):
        owner = self.start()
        self.wait_window()
        (self.root / 'exit').write_text('escape')
        self.finished(owner, disabled=False)
        self.assertFalse((self.root / 'disabled').exists())

    def test_quit_then_reopen_and_close_does_not_reuse_quit_request(self):
        owner = self.start()
        self.wait_window()
        (self.root / 'exit').write_text('0')
        self.finished(owner)
        (self.root / 'exit').unlink()
        reopened = self.start()
        pid = self.wait_window()
        os.kill(pid, signal.SIGTERM)
        self.finished(reopened, 256 - signal.SIGTERM, disabled=False)
        self.assertEqual(len((self.root / 'disabled').read_text().splitlines()), 1)
        self.assertFalse(any(path.is_dir() for path in self.root.glob('resource-monitor-*')))

    def test_supervisor_signal_closes_only_owned_terminal(self):
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        self.children.append(unrelated)
        owner = self.start()
        self.wait_window()
        owner.terminate()
        self.finished(owner, 128 + signal.SIGTERM, disabled=False)
        self.assertIsNone(unrelated.poll())

    def test_new_launch_waits_until_previous_cleanup_finishes(self):
        owner = self.start()
        self.wait_window()
        (self.root / 'hold-cleanup').touch()
        (self.root / 'exit').write_text('0')
        self.wait_for(lambda: (self.root / 'cleanup-started').exists())
        # The old Foot has exited, but its disable operation is still in flight.
        with patch.dict(os.environ, self.env):
            with launcher.instance_file() as contender:
                with self.assertRaises(BlockingIOError):
                    launcher.fcntl.flock(contender, launcher.fcntl.LOCK_EX | launcher.fcntl.LOCK_NB)
        pending = self.start()
        (self.root / 'exit').unlink()
        (self.root / 'hold-cleanup').unlink()
        # Do not use finished(owner) here: the next window may already exist.
        owner.communicate(timeout=8)
        self.assertEqual(owner.returncode, 0)
        self.wait_window()
        self.assertEqual(len((self.root / 'starts').read_text().splitlines()), 2)
        (self.root / 'exit').write_text('0')
        self.finished(pending)

    def test_stale_pid_file_is_ignored_without_a_live_lock(self):
        with patch.dict(os.environ, self.env):
            with launcher.instance_file() as lease:
                lease.write('1')
        owner = self.start()
        self.wait_window()
        (self.root / 'exit').write_text('0')
        self.finished(owner)


if __name__ == '__main__':
    unittest.main()
