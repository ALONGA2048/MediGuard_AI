"""Run the original camera/LED service for the HDMI kiosk, without SPI LCD."""
import importlib.util
import os
from pathlib import Path
import signal
import sys

ROOT = Path(__file__).resolve().parent


def load_hardware():
    for line in (ROOT / '.env').read_text(encoding='utf-8-sig').splitlines() if (ROOT / '.env').exists() else []:
        if line.strip() and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip())
    # Force LCD off even if an old .env was copied. Import never executes its main.
    os.environ['MEDILENS_LCD_ENABLED'] = 'false'
    os.environ['MEDILENS_LISTEN_HOST'] = '127.0.0.1'
    os.environ.setdefault('MEDILENS_CAPTURE_DIR', str(ROOT / 'data' / 'captures'))
    # Only the display stream is reduced; keep original Full HD capture/focus.
    os.environ.setdefault('MEDILENS_PREVIEW_WIDTH', '640')
    os.environ.setdefault('MEDILENS_PREVIEW_HEIGHT', '360')
    os.environ.setdefault('MEDILENS_PREVIEW_FPS', '3')
    source = Path(os.environ.get('MEDILENS_HARDWARE_SOURCE', str(ROOT.parent / 'raspberry_pi' / 'hardware.py')))
    if not source.is_file():
        raise SystemExit('找不到原 raspberry_pi/hardware.py；請連同該資料夾部署，或設定 MEDILENS_HARDWARE_SOURCE。')
    spec = importlib.util.spec_from_file_location('mediguard_original_hardware', source)
    hardware = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = hardware
    spec.loader.exec_module(hardware)
    return hardware


if __name__ == '__main__':
    os.umask(0o077)
    hardware = load_hardware()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        hardware.app.run(host='127.0.0.1', port=hardware.LISTEN_PORT,
                         threaded=True, debug=False, use_reloader=False)
    finally:
        hardware.cleanup()
