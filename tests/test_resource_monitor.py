"""Regression coverage for the optional, unprivileged resource monitor."""
import importlib.machinery
import importlib.util
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


monitor = load('resource_monitor', SOURCE / 'resource-monitor')
installer = load('resource_monitor_install', SOURCE / 'install.py')


class MonitorTests(unittest.TestCase):
    def test_selection_follows_identity_not_sorted_index(self):
        first = ((20, 100), ['20', '3', '1', 'S', 'first'])
        second = ((30, 200), ['30', '2', '1', 'S', 'second'])
        self.assertEqual(monitor.selected_index([second, first], first[0]), 1)
        self.assertIsNone(monitor.selected_index([((20, 999), first[1])], first[0]))

    def test_pid_reuse_refused_after_open_and_descriptor_closed(self):
        with patch.object(monitor.os, 'pidfd_open', return_value=7, create=True), \
             patch.object(monitor, 'process_identity', return_value=(20, 999)), \
             patch.object(monitor.signal, 'pidfd_send_signal', create=True) as send, \
             patch.object(monitor.os, 'close') as close:
            self.assertIn('changed', monitor.stop_process((20, 100)))
            send.assert_not_called()
            close.assert_called_once_with(7)

    def test_signal_bound_to_pidfd(self):
        with patch.object(monitor.os, 'pidfd_open', return_value=7, create=True), \
             patch.object(monitor, 'process_identity', return_value=(20, 100)), \
             patch.object(monitor.signal, 'pidfd_send_signal', create=True) as send, \
             patch.object(monitor.os, 'close') as close:
            self.assertIn('SIGTERM sent', monitor.stop_process((20, 100)))
            send.assert_called_once_with(7, monitor.signal.SIGTERM)
            close.assert_called_once_with(7)

    def test_protected_pids_and_unsupported_kernel(self):
        self.assertIn('Refusing', monitor.stop_process((1, 0)))
        self.assertIn('Refusing', monitor.stop_process((monitor.os.getpid(), 0)))
        with patch.object(monitor.os, 'pidfd_open', side_effect=OSError('unsupported'), create=True), \
             patch.object(monitor.signal, 'pidfd_send_signal', create=True) as send:
            self.assertIn('Could not safely', monitor.stop_process((20, 100)))
            send.assert_not_called()

    def test_missing_pidfd_api_is_safe(self):
        with patch.object(monitor, 'os') as platform:
            platform.getpid.return_value = 999
            del platform.pidfd_open
            self.assertIn('unavailable', monitor.stop_process((20, 100)))
            platform.kill.assert_not_called()

    def test_permission_failure_visible(self):
        with patch.object(monitor.os, 'pidfd_open', side_effect=PermissionError, create=True), \
             patch.object(monitor.signal, 'pidfd_send_signal', create=True):
            self.assertIn('Permission denied', monitor.stop_process((20, 100)))

    def test_scroll_keeps_selection_visible(self):
        self.assertEqual(monitor.viewport(20, 0, 5), 16)
        self.assertEqual(monitor.viewport(2, 16, 5), 2)

    def test_draw_clips_and_survives_resize(self):
        screen = Mock()
        screen.getmaxyx.return_value = (2, 8)
        monitor.put(screen, 8, 0, 'hidden')
        screen.addnstr.assert_not_called()
        monitor.put(screen, 0, 0, 'long text')
        screen.addnstr.assert_called_once_with(0, 0, 'long text', 7, 0)
        screen.addnstr.side_effect = monitor.curses.error
        monitor.put(screen, 0, 0, 'resized')

    def test_k_requires_separate_confirmation_and_cancel_never_signals(self):
        screen = Mock()
        screen.getmaxyx.return_value = (20, 70)
        screen.getch.side_effect = [-1, ord('j'), ord('K'), ord('n'), ord('q')]
        row = ((20, 100), ['20', '2', '1', 'S', 'example'])
        with patch.object(monitor, 'processes', return_value=[row]), \
             patch.object(monitor, 'read_cpu', return_value=(1, (1, 1))), \
             patch.object(monitor, 'read_memory', return_value=(1, 2)), \
             patch.object(monitor, 'stop_process') as stop, \
             patch.object(monitor.curses, 'curs_set'), patch.object(monitor.curses, 'mousemask'), \
             patch.object(monitor.curses, 'mouseinterval'):
            monitor.main(screen)
            stop.assert_not_called()

    def test_shrink_cancels_pending_confirmation_before_input(self):
        screen = Mock()
        size = [20, 70]
        keys = iter([-1, ord('j'), ord('K'), ord('y'), ord('q')])
        def key():
            value = next(keys)
            if value == ord('y'):
                size[:] = [5, 20]
            return value
        screen.getch.side_effect = key
        screen.getmaxyx.side_effect = lambda: tuple(size)
        row = ((20, 100), ['20', '2', '1', 'S', 'example'])
        with patch.object(monitor, 'processes', return_value=[row]), \
             patch.object(monitor, 'read_cpu', return_value=(1, (1, 1))), \
             patch.object(monitor, 'read_memory', return_value=(1, 2)), \
             patch.object(monitor, 'stop_process') as stop, \
             patch.object(monitor.curses, 'curs_set'), patch.object(monitor.curses, 'mousemask'), \
             patch.object(monitor.curses, 'mouseinterval'):
            monitor.main(screen)
            stop.assert_not_called()

    def test_touch_scroll_select_stop_and_confirm(self):
        screen = Mock()
        screen.getmaxyx.return_value = (10, 42)
        screen.getch.side_effect = [-1] + [monitor.curses.KEY_MOUSE] * 5 + [ord('q')]
        # Select first row, Down twice scrolls to third row, then Stop/Confirm.
        release = monitor.curses.BUTTON1_RELEASED
        clicks = [(0, 1, 4, 0, release), (0, 10, 8, 0, release),
                  (0, 10, 8, 0, release), (0, 20, 8, 0, release), (0, 2, 8, 0, release)]
        rows = [((pid, pid * 10), [str(pid), '2', '1', 'S', 'example']) for pid in (20, 30, 40)]
        with patch.object(monitor, 'processes', return_value=rows), \
             patch.object(monitor, 'read_cpu', return_value=(1, (1, 1))), \
             patch.object(monitor, 'read_memory', return_value=(1, 2)), \
             patch.object(monitor, 'stop_process', return_value='sent') as stop, \
             patch.object(monitor.curses, 'getmouse', side_effect=clicks), \
             patch.object(monitor.curses, 'curs_set'), patch.object(monitor.curses, 'mousemask'), \
             patch.object(monitor.curses, 'mouseinterval'):
            monitor.main(screen)
            stop.assert_called_once_with((40, 400))

    def test_mouse_wheel_moves_selection_and_confirmation_freezes_it(self):
        screen = Mock()
        screen.getmaxyx.return_value = (20, 70)
        screen.getch.side_effect = [
            -1, ord('j'), monitor.curses.KEY_MOUSE, ord('K'),
            monitor.curses.KEY_MOUSE, ord('y'), ord('q')]
        rows = [((pid, pid * 10), [str(pid), '2', '1', 'S', 'example'])
                for pid in (20, 30, 40)]
        wheel = getattr(monitor.curses, 'BUTTON5_PRESSED', 0)
        if not wheel:
            self.skipTest('terminal library has no mouse-wheel-down event')
        with ExitStack() as stack:
            for name, value in [('processes', rows), ('read_cpu', (1, (1, 1))),
                                ('read_memory', (1, 2))]:
                stack.enter_context(patch.object(monitor, name, return_value=value))
            for name in ('curs_set', 'mousemask', 'mouseinterval'):
                stack.enter_context(patch.object(monitor.curses, name))
            stack.enter_context(patch.object(monitor.curses, 'getmouse',
                                             return_value=(0, 0, 4, 0, wheel)))
            stop = stack.enter_context(patch.object(monitor, 'stop_process', return_value='sent'))
            monitor.main(screen)
        stop.assert_called_once_with((30, 300))

    def test_reordered_refresh_keeps_confirmed_process(self):
        screen = Mock()
        screen.getmaxyx.return_value = (20, 70)
        screen.getch.side_effect = [-1, ord('j'), ord('K'), ord('y'), ord('q')]
        first = ((20, 100), ['20', '2', '1', 'S', 'first'])
        second = ((30, 200), ['30', '1', '1', 'S', 'second'])
        with patch.object(monitor, 'processes', side_effect=[[first, second], [second, first], [second, first], [second, first]]), \
             patch.object(monitor.time, 'monotonic', side_effect=[10, 11, 12, 13]), \
             patch.object(monitor, 'read_cpu', return_value=(1, (1, 1))), \
             patch.object(monitor, 'read_memory', return_value=(1, 2)), \
             patch.object(monitor, 'stop_process', return_value='sent') as stop, \
             patch.object(monitor.curses, 'curs_set'), patch.object(monitor.curses, 'mousemask'), \
             patch.object(monitor.curses, 'mouseinterval'):
            monitor.main(screen)
            stop.assert_called_once_with(first[0])

    def test_confirm_signals_selected_identity_once(self):
        screen = Mock()
        screen.getmaxyx.return_value = (20, 70)
        screen.getch.side_effect = [-1, ord('j'), ord('K'), ord('y'), ord('q')]
        row = ((20, 100), ['20', '2', '1', 'S', 'example'])
        with patch.object(monitor, 'processes', return_value=[row]), \
             patch.object(monitor, 'read_cpu', return_value=(1, (1, 1))), \
             patch.object(monitor, 'read_memory', return_value=(1, 2)), \
             patch.object(monitor, 'stop_process', return_value='sent') as stop, \
             patch.object(monitor.curses, 'curs_set'), patch.object(monitor.curses, 'mousemask'), \
             patch.object(monitor.curses, 'mouseinterval'):
            monitor.main(screen)
            stop.assert_called_once_with((20, 100))


class KeyboardTests(unittest.TestCase):
    def run_keys(self, keys, size=(20, 70)):
        screen = Mock()
        screen.getmaxyx.return_value = size
        screen.getch.side_effect = keys
        row = ((20, 100), ['20', '2', '1', 'S', 'example'])
        with ExitStack() as stack:
            for name, value in [('processes', [row]), ('read_cpu', (1, (1, 1))),
                                ('read_memory', (1, 2))]:
                stack.enter_context(patch.object(monitor, name, return_value=value))
            # Ensure the first displayed frame has rows even in a new process
            # whose monotonic clock has not reached one second yet.
            stack.enter_context(patch.object(monitor.time, 'monotonic', return_value=100))
            stack.enter_context(patch.object(monitor.shutil, 'disk_usage',
                                             return_value=Mock(used=1, total=2)))
            for name in ('curs_set', 'mousemask', 'mouseinterval'):
                stack.enter_context(patch.object(monitor.curses, name))
            quit_request = stack.enter_context(patch.object(monitor, 'request_quit'))
            stop = stack.enter_context(patch.object(monitor, 'stop_process'))
            monitor.main(screen)
        return screen, quit_request, stop

    def test_escape_closes_only_window_at_normal_and_small_sizes(self):
        for size in ((20, 70), (5, 20)):
            with self.subTest(size=size):
                screen, quit_request, stop = self.run_keys([-1, 27], size)
                self.assertEqual(screen.getch.call_count, 2)
                quit_request.assert_not_called()
                stop.assert_not_called()

    def test_escape_cancels_confirmation_and_next_escape_closes_window(self):
        screen, quit_request, stop = self.run_keys([-1, ord('j'), ord('K'), 27, 27])
        self.assertEqual(screen.getch.call_count, 5)
        text = [call.args[2] for call in screen.addnstr.call_args_list]
        self.assertTrue(any('Stop PID 20' in line for line in text))
        self.assertIn('y: stop | n/Esc: cancel | q: quit both', text)
        quit_request.assert_not_called()
        stop.assert_not_called()

    def test_q_quits_both_during_confirmation_without_signaling_process(self):
        screen, quit_request, stop = self.run_keys([-1, ord('j'), ord('K'), ord('q')])
        self.assertEqual(screen.getch.call_count, 4)
        self.assertTrue(any('Stop PID 20' in call.args[2]
                            for call in screen.addnstr.call_args_list))
        quit_request.assert_called_once_with()
        stop.assert_not_called()

    def test_q_quits_both_at_normal_and_small_sizes(self):
        for size in ((20, 70), (5, 20)):
            with self.subTest(size=size):
                screen, quit_request, stop = self.run_keys([-1, ord('q')], size)
                self.assertEqual(screen.getch.call_count, 2)
                quit_request.assert_called_once_with()
                stop.assert_not_called()

    def test_stop_shortcut_and_quit_button_fit_minimum_window(self):
        screen, _, _ = self.run_keys([-1, 27], (10, 42))
        buttons = [call.args for call in screen.addnstr.call_args_list if call.args[0] == 8]
        self.assertEqual([args[2] for args in buttons],
                         ['[ Up ]', '[ Down ]', '[ Stop [K] ]', '[ Quit ]'])
        for _, left, text, limit, _ in buttons:
            self.assertGreaterEqual(limit, len(text))
            self.assertLessEqual(left + len(text), 41)
        self.assertIn('j/k: move | K: stop | q: quit | Esc: close',
                      [call.args[2] for call in screen.addnstr.call_args_list])


class InstallerTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(installer.os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        installer.os.environ.pop('XDG_DATA_HOME', None)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name) / 'home with spaces'
        self.home.mkdir()
        self.defaults = Path(self.directory.name) / 'defaults.json'
        self.base = {'version': 1, 'idle': {'lock': 0}, 'disabledPlugins': ['omarchy.lock'],
                     'bar': {'layout': {'left': [{'id': 'omarchy.menu'}], 'right': []}}}
        self.defaults.write_text(json.dumps(self.base))
        self.config = self.home / '.config/omarchy-ipad/shell.json'

    def test_missing_config_uses_complete_defaults_and_apps_entry(self):
        installer.install(SOURCE, self.home, self.defaults)
        config = json.loads(self.config.read_text())
        self.assertEqual(config['idle'], self.base['idle'])
        self.assertEqual(config['disabledPlugins'], ['omarchy.lock'])
        self.assertEqual(config['bar']['layout']['left'], [{'id': 'omarchy.menu'}])
        self.assertEqual(config['bar']['layout']['right'], [{'id': installer.PLUGIN_ID}])
        desktop = (self.home / '.local/share/applications/resource-monitor.desktop').read_text()
        self.assertIn('Exec="' + str(self.home / '.local/bin/resource-monitor-launch') + '"', desktop)
        launcher = (self.home / '.local/bin/resource-monitor-launch').read_text()
        self.assertEqual(launcher, (SOURCE / 'resource-monitor-launch').read_text())
        widget = (self.home / '.config/omarchy/plugins' / installer.PLUGIN_ID / 'BarWidget.qml').read_text()
        self.assertIn('/.local/bin/resource-monitor-launch', widget)
        self.assertIn('Util.shellQuote(root.executable)', widget)

    def test_idempotent_and_preserves_existing_placement(self):
        self.base['bar']['layout']['left'].append({'id': installer.PLUGIN_ID, 'custom': True})
        self.config.parent.mkdir(parents=True)
        self.config.write_text(json.dumps(self.base))
        installer.install(SOURCE, self.home, self.defaults)
        installer.install(SOURCE, self.home, self.defaults)
        self.assertEqual(json.loads(self.config.read_text()), self.base)

    def test_malformed_config_fails_before_installation(self):
        self.config.parent.mkdir(parents=True)
        self.config.write_text('{invalid')
        with self.assertRaises(ValueError):
            installer.install(SOURCE, self.home, self.defaults)
        self.assertEqual(self.config.read_text(), '{invalid')
        self.assertFalse((self.home / '.local/bin/resource-monitor').exists())

    def test_missing_defaults_does_not_invent_partial_config(self):
        with self.assertRaises(ValueError):
            installer.install(SOURCE, self.home, self.home / 'missing')
        self.assertFalse(self.config.exists())

    def test_failed_replace_leaves_original_and_cleans_temporary(self):
        self.config.parent.mkdir(parents=True)
        self.config.write_text('original')
        with patch.object(installer.os, 'replace', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                installer.atomic_write(self.config, b'changed')
        self.assertEqual(self.config.read_text(), 'original')
        self.assertEqual(list(self.config.parent.iterdir()), [self.config])

    def test_destination_conflicts_leave_existing_installation_unchanged(self):
        installer.install(SOURCE, self.home, self.defaults)
        executable = self.home / '.local/bin/resource-monitor'
        executable.write_text('previous monitor')
        manifest = self.home / '.config/omarchy/plugins' / installer.PLUGIN_ID / 'manifest.json'
        config_before = self.config.read_bytes()
        manifest.unlink()
        for conflict in ('symlink', 'directory'):
            with self.subTest(conflict=conflict):
                if conflict == 'symlink':
                    manifest.symlink_to(self.defaults)
                else:
                    manifest.mkdir()
                with self.assertRaises(ValueError):
                    installer.install(SOURCE, self.home, self.defaults)
                self.assertEqual(executable.read_text(), 'previous monitor')
                self.assertEqual(self.config.read_bytes(), config_before)
                self.assertEqual(json.loads(self.defaults.read_text()), self.base)
                if conflict == 'symlink':
                    manifest.unlink()
                else:
                    manifest.rmdir()

    def test_config_created_during_first_install_is_not_overwritten(self):
        write = installer.atomic_write
        concurrent = json.dumps(dict(self.base, concurrent=True)).encode()

        def write_with_config_change(path, data, mode=0o644):
            write(path, data, mode)
            self.config.parent.mkdir(parents=True, exist_ok=True)
            self.config.write_bytes(concurrent)

        with patch.object(installer, 'atomic_write', side_effect=write_with_config_change):
            with self.assertRaisesRegex(ValueError, 'changed during installation'):
                installer.install(SOURCE, self.home, self.defaults)
        self.assertEqual(self.config.read_bytes(), concurrent)

    def test_linked_config_is_not_replaced(self):
        self.config.parent.mkdir(parents=True)
        self.config.symlink_to(self.defaults)
        with self.assertRaises(ValueError):
            installer.install(SOURCE, self.home, self.defaults)
        self.assertEqual(json.loads(self.defaults.read_text()), self.base)


class CommandLineTests(unittest.TestCase):
    def run_monitor(self, *args):
        return subprocess.run([sys.executable, str(SOURCE / 'resource-monitor'), *args],
                              input='', capture_output=True, text=True)

    def test_help_works_without_a_terminal(self):
        result = self.run_monitor('--help')
        self.assertEqual(result.returncode, 0)
        self.assertIn('--stats', result.stdout)

    def test_unknown_option_and_missing_terminal_report_actionable_errors(self):
        result = self.run_monitor('--unknown')
        self.assertEqual(result.returncode, 2)
        self.assertIn('unrecognized arguments', result.stderr)
        result = self.run_monitor()
        self.assertEqual(result.returncode, 1)
        self.assertIn('interactive terminal', result.stderr)
        self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
