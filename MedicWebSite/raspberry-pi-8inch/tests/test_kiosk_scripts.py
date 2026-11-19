"""Launcher checks using temporary profiles and fake browser/network commands."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def embedded_python(script):
    return re.search(r"<<'PY'\n(.*?)\nPY", script.read_text(encoding='utf-8'), re.S).group(1)


class LauncherConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def port(self, text='', override=None):
        path = self.directory / '.env'
        path.write_text(text, encoding='utf-8')
        env = os.environ.copy()
        env['PYTHONUTF8'] = '1'
        env.pop('POS_PORT', None)
        if override is not None:
            env['POS_PORT'] = override
        return subprocess.run([sys.executable, '-c', embedded_python(ROOT / 'scripts/kiosk.sh'), str(path)],
                              env=env, text=True, encoding='utf-8', capture_output=True)

    def test_default_and_bom_port(self):
        self.assertEqual(self.port().stdout.strip(), '8088')
        self.assertEqual(self.port('\ufeff# settings\n POS_PORT = 8091\n').stdout.strip(), '8091')

    def test_environment_precedes_file(self):
        self.assertEqual(self.port('POS_PORT=8091\n', '8092').stdout.strip(), '8092')

    def test_first_port_matches_server_setdefault(self):
        self.assertEqual(self.port('POS_PORT=8091\nPOS_PORT=8092\n').stdout.strip(), '8091')

    def test_bad_port_rejected(self):
        for value in ('0', '65536', 'abc', ''):
            with self.subTest(value=value):
                self.assertNotEqual(self.port('POS_PORT=' + value).returncode, 0)

    def test_env_is_not_shell_code(self):
        sentinel = self.directory / 'should-not-exist'
        result = self.port(f'POS_SYNC_TOKEN=$(touch {sentinel})\nPOS_PORT=8088\n')
        self.assertEqual(result.returncode, 0)
        self.assertFalse(sentinel.exists())

    def test_openbox_migration_is_preserving_and_idempotent(self):
        path = self.directory / 'autostart'
        old = ('# user setting\nxsetroot -solid black &\n'
               'chromium "file://$HOME/browser-test.html" \\\n'
               '  > "$HOME/browser-test.log" 2>&1 &\n'
               '"$HOME/MediGuard_AI/MedicWebSite/raspberry-pi-8inch/scripts/kiosk.sh" \\\n'
               '  >> "$HOME/mediguard-kiosk.log" 2>&1 &\n')
        path.write_text(old)
        args = [sys.executable, '-c', embedded_python(ROOT / 'scripts/install.sh'),
                str(path), '/home/master/app/scripts/kiosk.sh']
        subprocess.run(args, check=True)
        first = path.read_text(encoding='utf-8')
        self.assertIn('xsetroot -solid black &', first)
        self.assertNotIn('browser-test', first)
        self.assertEqual(first.count('/home/master/app/scripts/kiosk.sh'), 1)
        self.assertNotIn('>>', first)
        self.assertEqual(next(self.directory.glob('autostart.backup-*')).read_text(encoding='utf-8'), old)
        subprocess.run(args, check=True)
        self.assertEqual(path.read_text(encoding='utf-8'), first)
        self.assertEqual(len(list(self.directory.glob('autostart.backup-*'))), 1)


class LauncherExecutionTests(unittest.TestCase):
    def setUp(self):
        if os.name != 'nt' and os.geteuid() == 0:
            self.skipTest('Browser launcher intentionally refuses root')
        self.bash = shutil.which('bash')
        if os.name == 'nt':
            candidate = Path('C:/Program Files/Git/bin/bash.exe')
            self.bash = str(candidate) if candidate.exists() else None
        if not self.bash:
            self.skipTest('Bash unavailable')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.bin = self.directory / 'bin'
        self.bin.mkdir()
        (self.directory / 'scripts').mkdir()
        shutil.copy2(ROOT / 'scripts/kiosk.sh', self.directory / 'scripts/kiosk.sh')
        self.env = os.environ.copy()
        self.env.update(HOME=self.directory.as_posix(), XDG_STATE_HOME='', XDG_RUNTIME_DIR='',
                        DISPLAY=':test', WAYLAND_DISPLAY='', MOCK_BIN=self.bin.as_posix(),
                        PYTHONUTF8='1', TEST_PYTHON=Path(sys.executable).as_posix(), POS_PORT='8099',
                        KIOSK_DISABLE_GPU='0', KIOSK_RESTART='0', KIOSK_READY_TIMEOUT='1')
        for key in ('CHROMIUM_BIN', 'KIOSK_PROFILE'):
            self.env.pop(key, None)
        self.mock('python3', 'exec "$TEST_PYTHON" "$@"')
        self.mock('curl', 'exit 0')
        # Mock locking here; these tests do not claim to verify kernel flock behavior.
        self.mock('flock', 'exit 0')
        self.mock('xset', 'exit 0')
        self.mock('chromium', 'printf "%s\\n" "$@" > "$HOME/browser-args"')

    def mock(self, name, body):
        path = self.bin / name
        path.write_text('#!/usr/bin/env bash\n' + body + '\n', newline='\n')
        path.chmod(0o755)

    def launch(self, script='kiosk.sh'):
        setup = 'cd "$HOME"; export PATH="$MOCK_BIN:$PATH"; bash scripts/' + script
        if os.name == 'nt':
            setup = 'MOCK_BIN=$(cygpath -u "$MOCK_BIN"); ' + setup
        return subprocess.run([self.bash, '-c', setup], env=self.env, text=True,
                              encoding='utf-8', capture_output=True, timeout=15)

    def test_native_x11_single_browser_and_port(self):
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        args = (self.directory / 'browser-args').read_text(encoding='utf-8')
        self.assertIn('--ozone-platform=x11', args)
        self.assertIn('http://127.0.0.1:8099', args)
        self.assertNotIn('--disable-gpu\n', args)
        self.assertNotIn('--no-sandbox', args)
        self.assertIn('--disk-cache-size=33554432', args)

    def test_gpu_diagnostic_is_opt_in(self):
        self.env['KIOSK_DISABLE_GPU'] = '1'
        self.assertEqual(self.launch().returncode, 0)
        self.assertIn('--disable-gpu\n', (self.directory / 'browser-args').read_text(encoding='utf-8'))

    def test_no_gui_exits_before_browser(self):
        self.env['DISPLAY'] = ''
        self.assertNotEqual(self.launch().returncode, 0)
        self.assertFalse((self.directory / 'browser-args').exists())

    def test_api_failure_times_out_without_browser(self):
        self.mock('curl', 'exit 1')
        self.assertNotEqual(self.launch().returncode, 0)
        self.assertFalse((self.directory / 'browser-args').exists())
        log = self.directory / '.local/state/mediguard/kiosk.log'
        self.assertIn('mediguard-pos.service', log.read_text(encoding='utf-8'))

    def test_supervision_stops_fast_crash(self):
        self.env['KIOSK_RESTART'] = '1'
        self.mock('chromium', 'exit 42')
        self.assertNotEqual(self.launch().returncode, 0)
        log = self.directory / '.local/state/mediguard/kiosk.log'
        self.assertIn('Chromium exited: 42', log.read_text(encoding='utf-8'))

    def test_install_services_only_without_package_commands(self):
        script = (ROOT / 'scripts/install.sh').read_text(encoding='utf-8')
        # Substitute only distro identification in this isolated fixture.
        script = script.replace('source /etc/os-release', 'ID=raspbian')
        (self.directory / 'scripts/install.sh').write_text(script, encoding='utf-8', newline='\n')
        (self.directory / '.env.example').write_text('POS_PORT=8088\n')
        self.env.update(KIOSK_DESKTOP='openbox', SKIP_PACKAGE_INSTALL='1')
        for command in ('openbox-session', 'Xorg'):
            self.mock(command, 'exit 0')
        self.mock('sudo', '''case "$1" in
install) cp "${@: -2:1}" "$HOME/installed-service" ;;
systemctl) printf '%s\\n' "$*" >> "$HOME/systemctl-calls" ;;
*) echo "Unexpected privileged command: $*" >&2; exit 99 ;;
esac''')
        first = self.launch('install.sh')
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue((self.directory / 'installed-service').exists())
        config = self.directory / '.config/openbox/autostart'
        self.assertEqual(config.read_text().count('# BEGIN MEDIGUARD KIOSK'), 1)
        desktop = self.directory / '.config/autostart/mediguard-pos.desktop'
        self.assertIn('Hidden=true', desktop.read_text())
        self.assertEqual(self.launch('install.sh').returncode, 0)
        self.assertEqual(config.read_text().count('# BEGIN MEDIGUARD KIOSK'), 1)


if __name__ == '__main__':
    unittest.main()
