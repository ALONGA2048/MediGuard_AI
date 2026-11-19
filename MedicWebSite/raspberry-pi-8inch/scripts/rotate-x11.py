#!/usr/bin/env python3
"""Rotate a single X11 display and its USB touchscreen before Chromium starts."""
import argparse
import os
import re
import shutil
import subprocess
import sys

MATRICES = {
    'normal': (1, 0, 0, 0, 1, 0, 0, 0, 1),
    'left': (0, -1, 1, 1, 0, 0, 0, 0, 1),
    'right': (0, 1, 0, -1, 0, 1, 0, 0, 1),
    'inverted': (-1, 0, 1, 0, -1, 1, 0, 0, 1),
}


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=10)


def active_outputs(query):
    return [line.split()[0] for line in query.splitlines()
            if re.match(r'^\S+ connected\b', line)
            and re.search(r'\b\d+x\d+\+\d+\+\d+\b', line)]


def touchscreens():
    if not shutil.which('xinput') or not shutil.which('udevadm'):
        return []
    devices = []
    for device in run('xinput', '--list', '--id-only').splitlines():
        device = device.strip()
        if not device.isdigit():
            continue
        try:
            props = run('xinput', '--list-props', device)
            node = re.search(r'Device Node \(\d+\):\s*"(/dev/input/event\d+)"', props)
            if node and 'Coordinate Transformation Matrix' in props:
                info = run('udevadm', 'info', '--query=property', '--name=' + node.group(1))
                if 'ID_INPUT_TOUCHSCREEN=1' in info.splitlines():
                    devices.append(device)
        except subprocess.SubprocessError:
            continue
    return devices


def main():
    parser = argparse.ArgumentParser(description='Openbox／X11 單螢幕與 USB 觸控旋轉')
    parser.add_argument('--rotation', choices=MATRICES, default=os.environ.get('KIOSK_ROTATION', 'right'))
    args = parser.parse_args()
    if args.rotation not in MATRICES:
        parser.error('KIOSK_ROTATION 必須是 normal、left、right 或 inverted')
    if not os.environ.get('DISPLAY'):
        parser.error('需要 X11 DISPLAY；請由 Openbox 自啟執行，不要 sudo。')
    if not shutil.which('xrandr'):
        parser.error('缺少 xrandr，請安裝 x11-xserver-utils。')
    try:
        outputs = active_outputs(run('xrandr', '--query'))
        if len(outputs) != 1:
            parser.error('只支援一個啟用中的螢幕；未變更顯示設定。')
        output = outputs[0]
        explicit = os.environ.get('KIOSK_TOUCH_DEVICE')
        devices = [explicit] if explicit else touchscreens()
        if devices and not shutil.which('xinput'):
            parser.error('缺少 xinput，無法對應觸控。')
        # Validate explicit device and property before changing display orientation.
        for device in devices:
            if 'Coordinate Transformation Matrix' not in run('xinput', '--list-props', device):
                parser.error('指定裝置沒有 Coordinate Transformation Matrix；未變更顯示設定。')
        run('xrandr', '--output', output, '--rotate', args.rotation)
        print(f'X11 output {output}: {args.rotation}', flush=True)
        for device in devices:
            run('xinput', '--set-prop', device, 'Coordinate Transformation Matrix',
                *(str(value) for value in MATRICES[args.rotation]))
            print(f'Touchscreen {device}: {args.rotation}', flush=True)
        if not devices:
            print('未自動找到觸控裝置；請檢查 USB 或用 KIOSK_TOUCH_DEVICE 指定 xinput 裝置名稱。', flush=True)
    except (subprocess.SubprocessError, OSError) as error:
        print(f'X11 旋轉失敗：{error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
