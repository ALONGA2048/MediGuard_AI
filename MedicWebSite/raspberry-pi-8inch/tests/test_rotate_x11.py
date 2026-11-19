import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('rotate_x11', Path(__file__).resolve().parents[1] / 'scripts/rotate-x11.py')
rotate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rotate)


class RotationTests(unittest.TestCase):
    def test_only_active_connected_output(self):
        query = ('HDMI-1 connected primary 1280x800+0+0 (normal left right)\n'
                 'HDMI-2 disconnected (normal left right)\nDP-1 connected (normal left right)\n')
        self.assertEqual(rotate.active_outputs(query), ['HDMI-1'])

    def test_repeated_rotation_uses_absolute_matrix(self):
        calls = []

        def fake_run(*args):
            calls.append(args)
            if args == ('xrandr', '--query'):
                return 'HDMI-1 connected primary 1280x800+0+0 (normal left right)\n'
            if args[:2] == ('xinput', '--list-props'):
                return 'Coordinate Transformation Matrix (1): 1 0 0 0 1 0 0 0 1\n'
            return ''

        with patch.dict(os.environ, {'DISPLAY': ':test', 'KIOSK_TOUCH_DEVICE': 'USB Touch'}), \
             patch('sys.argv', ['rotate-x11.py', '--rotation', 'right']), \
             patch.object(rotate.shutil, 'which', return_value='/fake/bin'), \
             patch.object(rotate, 'run', side_effect=fake_run):
            self.assertEqual(rotate.main(), 0)
            self.assertEqual(rotate.main(), 0)
        matrices = [c for c in calls if c[:2] == ('xinput', '--set-prop')]
        self.assertEqual(len(matrices), 2)
        self.assertEqual(matrices[0], matrices[1])
        self.assertEqual(matrices[0][-9:], tuple(map(str, rotate.MATRICES['right'])))

    def test_multiple_displays_refused_before_mutation(self):
        query = 'HDMI-1 connected 1280x800+0+0\nHDMI-2 connected 1280x800+1280+0\n'
        with patch.dict(os.environ, {'DISPLAY': ':test'}), \
             patch('sys.argv', ['rotate-x11.py']), \
             patch.object(rotate.shutil, 'which', return_value='/fake/bin'), \
             patch.object(rotate, 'run', return_value=query) as call:
            with self.assertRaises(SystemExit):
                rotate.main()
        self.assertEqual(call.call_count, 1)

    def test_touch_detection_does_not_rotate_mouse(self):
        def fake_run(*args):
            if args == ('xinput', '--list', '--id-only'):
                return '10\n11\n'
            if args[:2] == ('xinput', '--list-props'):
                return f'Coordinate Transformation Matrix (1): 1 0 0 0 1 0 0 0 1\nDevice Node (2): "/dev/input/event{args[2]}"'
            if args[-1].endswith('event10'):
                return 'ID_INPUT_TOUCHSCREEN=1\n'
            return 'ID_INPUT_MOUSE=1\n'

        with patch.object(rotate.shutil, 'which', return_value='/fake/bin'), \
             patch.object(rotate, 'run', side_effect=fake_run):
            self.assertEqual(rotate.touchscreens(), ['10'])


if __name__ == '__main__':
    unittest.main()
