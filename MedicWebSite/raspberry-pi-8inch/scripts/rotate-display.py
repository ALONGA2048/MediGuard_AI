#!/usr/bin/env python3
"""Rotate one active GNOME monitor over the logged-in user's session D-Bus."""
import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description='GNOME 單螢幕旋轉（可由同一桌面使用者的 SSH 執行）')
    parser.add_argument('--rotation', type=int, choices=(0, 90, 180, 270), help='省略時只讀取狀態；0 還原橫向')
    parser.add_argument('--temporary', action='store_true', help='僅暫時套用，不要求保存設定')
    args = parser.parse_args()
    if os.getuid() == 0:
        sys.exit('請使用已登入 GNOME 桌面的帳號執行，不要 sudo。')
    bus = Path(f'/run/user/{os.getuid()}/bus')
    if not bus.exists():
        sys.exit('找不到使用者 session bus；請先讓本機 GNOME 桌面登入同一帳號。')
    # Use the desktop user's bus explicitly; an SSH session may have other env vars.
    os.environ['XDG_RUNTIME_DIR'] = str(bus.parent)
    os.environ['DBUS_SESSION_BUS_ADDRESS'] = f'unix:path={bus}'
    try:
        import gi
        gi.require_version('Gio', '2.0')
        from gi.repository import Gio, GLib
    except ImportError:
        sys.exit('缺少 PyGObject，請先 sudo apt install python3-gi，再用 /usr/bin/python3 執行。')
    try:
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)

        def call(method, parameters=None):
            return connection.call_sync(
                'org.gnome.Mutter.DisplayConfig', '/org/gnome/Mutter/DisplayConfig',
                'org.gnome.Mutter.DisplayConfig', method, parameters, None,
                Gio.DBusCallFlags.NONE, 10000, None)

        serial, monitors, logical, properties = call('GetCurrentState').unpack()
        for spec, modes, _ in monitors:
            active = next((m for m in modes if m[6].get('is-current')), None)
            if active:
                print(f'{spec[0]}: 模式 {active[1]}×{active[2]} @ {active[3]:.2f} Hz')
        for x, y, scale, transform, primary, specs, _ in logical:
            print(f'目前方向={transform * 90 if transform < 4 else transform}，縮放={scale}，輸出={", ".join(s[0] for s in specs)}')
        if args.rotation is None:
            return
        if len(logical) != 1 or len(logical[0][5]) != 1:
            sys.exit('此工具限定單一啟用螢幕、不支援鏡像／多螢幕；請先從桌面設定。未修改設定。')
        x, y, scale, _, primary, specs, _ = logical[0]
        spec = specs[0]
        monitor = next(m for m in monitors if tuple(m[0]) == tuple(spec))
        mode = next((m for m in monitor[1] if m[6].get('is-current')), None)
        if mode is None:
            sys.exit('找不到目前顯示模式。未修改設定。')
        monitor_properties = {}
        if 'is-underscanning' in monitor[2]:
            monitor_properties['enable_underscanning'] = GLib.Variant('b', monitor[2]['is-underscanning'])
        global_properties = {}
        if properties.get('supports-changing-layout-mode') and 'layout-mode' in properties:
            global_properties['layout-mode'] = GLib.Variant('u', properties['layout-mode'])
        config = [(0, 0, scale, args.rotation // 90, primary,
                   [(spec[0], mode[0], monitor_properties)])]
        signature = '(uua(iiduba(ssa{sv}))a{sv})'
        # Ask Mutter to validate before applying. Keep current mode and scale.
        call('ApplyMonitorsConfig', GLib.Variant(signature, (serial, 0, config, global_properties)))
        method = 1 if args.temporary else 2
        call('ApplyMonitorsConfig', GLib.Variant(signature, (serial, method, config, global_properties)))
        _, _, updated, _ = call('GetCurrentState').unpack()
        if len(updated) != 1 or updated[0][3] != args.rotation // 90:
            sys.exit('設定已送出，但讀回方向不一致；請檢查桌面顯示狀態。')
        print(f'已套用 {args.rotation} 度；' + ('暫時設定。' if args.temporary else '已要求 GNOME 保存；請在重新登入／重開機後確認。'))
    except GLib.Error as error:
        sys.exit(f'GNOME 顯示設定失敗：{error.message}\n請確認本機桌面已登入相同帳號，且目前使用 GNOME／Mutter。')


if __name__ == '__main__':
    main()
