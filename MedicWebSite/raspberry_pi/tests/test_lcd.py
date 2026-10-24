"""LCD regression checks against the user's hardware-tested startup sequence."""

import ast
import os
from pathlib import Path
import time
import types
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageFont


def load_lcd_class():
    source = Path(__file__).resolve().parents[1] / "hardware.py"
    module = ast.parse(source.read_text(encoding="utf-8"))
    definition = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "SpiLcd")
    namespace = dict(os=os, time=time, LED_PIN=18, CURRENT_DIR=Path("."))
    exec(compile(ast.Module(body=[definition], type_ignores=[]), str(source), "exec"), namespace)
    return namespace["SpiLcd"]


SpiLcd = load_lcd_class()


class LcdTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_initialization_matches_hardware_tested_commands_delays_and_pins(self):
        spi, gpio = Mock(), Mock()
        modules = {"spidev": types.SimpleNamespace(SpiDev=Mock(return_value=spi)),
                   "gpiozero": types.SimpleNamespace(OutputDevice=gpio)}
        # A leftover setting from an earlier version must not select old logic.
        with patch.dict(os.environ, {"MEDILENS_LCD_DRIVER": "ili9341"}):
            screen = SpiLcd()
        self.assertEqual(screen.driver, "st7789")
        with patch.dict("sys.modules", modules), patch.object(time, "sleep") as sleep:
            screen._initialize()
        spi.open.assert_called_once_with(0, 0)
        self.assertEqual((spi.max_speed_hz, spi.mode, spi.bits_per_word), (8_000_000, 0, 8))
        self.assertEqual([call.args for call in gpio.call_args_list], [(25,), (24,)])
        self.assertEqual([call.args[0] for call in spi.writebytes.call_args_list],
                         [[0x01], [0x11], [0x3A], [0x36], [0x20], [0x13], [0x29]])
        self.assertEqual([call.args[0] for call in spi.writebytes2.call_args_list], [[0x55], [0x60]])
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.05, 0.05, 0.15, 0.15, 0.12, 0.1])

    def test_frame_uses_one_window_and_complete_4096_byte_chunks(self):
        screen = SpiLcd()
        screen.spi, screen.dc = Mock(), Mock()
        image = Image.new("RGB", (320, 240), "white")
        for x, color in enumerate(((255, 0, 0), (0, 255, 0), (0, 0, 255), (0, 0, 0))):
            image.putpixel((x, 0), color)
        screen._display(image)
        self.assertEqual([call.args[0] for call in screen.spi.writebytes.call_args_list], [[0x2A], [0x2B], [0x2C]])
        writes = [bytes(call.args[0]) for call in screen.spi.writebytes2.call_args_list]
        self.assertEqual(writes[:2], [b"\x00\x00\x01\x3f", b"\x00\x00\x00\xef"])
        chunks = writes[2:]
        self.assertEqual([len(chunk) for chunk in chunks], [4096] * 37 + [2048])
        framebuffer = b"".join(chunks)
        self.assertEqual(len(framebuffer), 153600)
        self.assertEqual(framebuffer[:10], b"\xf8\x00\x07\xe0\x00\x1f\x00\x00\xff\xff")
        self.assertEqual(framebuffer[-2:], b"\xff\xff")

    def test_success_keeps_resources_and_never_redraws_until_stop(self):
        screen = SpiLcd()
        resources = [Mock(), Mock(), Mock()]
        screen.spi, screen.dc, screen.reset = resources
        image = Mock()
        with patch.object(screen, "_initialize") as initialize, \
             patch.object(screen, "_qr_frame", return_value=image), \
             patch.object(screen, "_display") as display:
            screen.start()
            self.assertEqual(screen.state["status"], "ready")
            screen.start()
            initialize.assert_called_once()
            display.assert_called_once_with(image)
            for resource in resources:
                resource.close.assert_not_called()
        screen.stop()
        screen.stop()
        for resource in resources:
            resource.close.assert_called_once()

    def test_qr_layout_matches_supplied_black_screen_title_and_130px_code(self):
        qr = Mock()
        qr.make_image.return_value = Image.new("RGB", (200, 200), "white")
        factory = Mock(return_value=qr)
        module = types.SimpleNamespace(QRCode=factory, constants=types.SimpleNamespace(ERROR_CORRECT_M=0))
        font = ImageFont.load_default()
        with patch.dict("sys.modules", {"qrcode": module}), patch.object(ImageFont, "truetype", return_value=font) as load_font:
            image = SpiLcd._qr_frame("http://210.240.160.152:3001")
        factory.assert_called_once_with(version=None, error_correction=0, box_size=6, border=3)
        qr.add_data.assert_called_once_with("http://210.240.160.152:3001")
        load_font.assert_called_once_with("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 24)
        self.assertEqual(image.size, (320, 240))
        self.assertEqual(image.getpixel((0, 0)), (0, 0, 0))
        self.assertEqual(image.getpixel((95, 60)), (255, 255, 255))
        self.assertEqual(image.getpixel((224, 189)), (255, 255, 255))
        self.assertEqual(image.getpixel((225, 190)), (0, 0, 0))

    def test_gpio_conflict_fails_before_allocating_pins(self):
        screen, gpio = SpiLcd(), Mock()
        modules = {"spidev": types.SimpleNamespace(), "gpiozero": types.SimpleNamespace(OutputDevice=gpio)}
        with patch.dict(os.environ, {"MEDILENS_LCD_DC": "18"}), patch.dict("sys.modules", modules):
            with self.assertRaisesRegex(ValueError, "conflict"):
                screen._initialize()
        gpio.assert_not_called()

    def test_optional_display_failure_is_reported_and_releases_resources(self):
        screen = SpiLcd()
        resources = [Mock(), Mock(), Mock()]
        screen.spi, screen.dc, screen.reset = resources
        with patch.object(screen, "_initialize", side_effect=ImportError("missing spidev")):
            screen.start()
        self.assertEqual(screen.state["status"], "failed")
        self.assertIn("missing spidev", screen.state["error"])
        for resource in resources:
            resource.close.assert_called_once()

    def test_disabled_display_skips_initialization(self):
        screen = SpiLcd()
        with patch.dict(os.environ, {"MEDILENS_LCD_ENABLED": "false"}), patch.object(screen, "_initialize") as initialize:
            screen.start()
        initialize.assert_not_called()
        self.assertEqual(screen.state["status"], "disabled")

    def test_service_shows_lcd_before_entering_flask(self):
        source = Path(__file__).resolve().parents[1] / "hardware.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        main = tree.body[-1]
        lcd, app = Mock(), Mock()
        def run(**_kwargs):
            lcd.start.assert_called_once()
            lcd.stop.assert_not_called()
        app.run.side_effect = run
        namespace = dict(__name__="__main__", DEVICE_TOKEN="test", LISTEN_PORT=5000,
                         WEBSITE_ORIGINS=set(), CONTROLLED_LED_INDEXES=(), RESERVED_LED_INDEXES=(),
                         RESERVED_LED_RGB=(), FIXED_LIGHT_MODE="white", FIXED_LIGHT_BRIGHTNESS=85,
                         CAMERA_1_INDEX=0, CAMERA_2_INDEX=2, LISTEN_HOST="0.0.0.0", lcd=lcd, app=app)
        exec(compile(ast.Module(body=[main], type_ignores=[]), str(source), "exec"), namespace)
        app.run.assert_called_once()
        lcd.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()