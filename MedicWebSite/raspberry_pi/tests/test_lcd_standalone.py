"""Standalone LCD geometry and pixel transfers without SPI/GPIO hardware."""

import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from PIL import Image


path = Path(__file__).resolve().parents[1] / "lcd_test.py"
spec = importlib.util.spec_from_file_location("standalone_lcd", path)
lcd_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lcd_module)


class StandaloneLcdTests(unittest.TestCase):
    def test_static_display_sends_once_then_only_waits(self):
        lcd = lcd_module.ILI9341(rotation_mode="software")
        lcd.open, lcd.initialize, lcd.clear, lcd.show_image, lcd.close = (Mock() for _ in range(5))
        lcd.show_image.return_value = 153600
        image = Mock()
        waits = 0

        def sleep(_seconds):
            nonlocal waits
            # Multiple hold intervals must not reinitialize, clear, redraw,
            # or release the RESET pin while the process is still running.
            waits += 1
            lcd.initialize.assert_called_once()
            lcd.show_image.assert_called_once_with(image)
            lcd.clear.assert_not_called()
            lcd.close.assert_not_called()
            if waits == 3:
                raise KeyboardInterrupt

        with patch("sys.argv", ["lcd_test.py", "--pattern", "test"]), \
             patch.object(lcd_module, "ILI9341", return_value=lcd), \
             patch.object(lcd_module, "create_screen", return_value=image), \
             patch.object(lcd_module.time, "sleep", side_effect=sleep), \
             patch("sys.stdout", new_callable=io.StringIO):
            lcd_module.main()
        self.assertEqual(waits, 3)
        lcd.close.assert_called_once()

    def test_all_rotations_fill_exact_memory_bounds_in_both_modes(self):
        for mode in ("software", "hardware"):
            for rotation in lcd_module.ROTATIONS:
                with self.subTest(mode=mode, rotation=rotation):
                    lcd = lcd_module.ILI9341(rotation, rotation_mode=mode)
                    lcd.spi, lcd.dc, lcd.reset = Mock(), Mock(), Mock()
                    with patch.object(lcd_module.time, "sleep"):
                        lcd.initialize()
                    calls = lcd.spi.mock_calls
                    index = next(i for i, call in enumerate(calls)
                                 if call[0] == "writebytes" and call.args[0] == [0x36])
                    self.assertEqual(calls[index + 1].args[0], bytes([lcd.madctl]))
                    lcd.spi.reset_mock()
                    self.assertEqual(lcd.show_image(Image.new("RGB", (lcd.width, lcd.height), "red")), 153600)
                    writes = [bytes(call.args[0]) for call in lcd.spi.writebytes2.call_args_list]
                    rows = [data for data in writes if len(data) == lcd.memory_width * 2]
                    self.assertEqual(len(rows), lcd.memory_height)
                    self.assertTrue(all(row == b"\xf8\x00" * lcd.memory_width for row in rows))
                    self.assertEqual(writes[0], b"\x00\x00" + (lcd.memory_width - 1).to_bytes(2, "big"))
                    self.assertEqual(writes[-2], (lcd.memory_height - 1).to_bytes(2, "big") * 2)
                    if mode == "software":
                        self.assertEqual((lcd.madctl, lcd.memory_width, lcd.memory_height), (0x48, 240, 320))

    def test_software_landscape_corner_placement(self):
        for rotation, targets in ((90, ((0, 319), (0, 0), (239, 319), (239, 0))),
                                  (270, ((239, 0), (239, 319), (0, 0), (0, 319)))):
            with self.subTest(rotation=rotation):
                lcd = lcd_module.ILI9341(rotation, rotation_mode="software")
                image = Image.new("RGB", (320, 240))
                colors = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255))
                for point, color in zip(((0, 0), (319, 0), (0, 239), (319, 239)), colors):
                    image.putpixel(point, color)
                native = lcd.to_memory_image(image)
                self.assertEqual(native.size, (240, 320))
                for target, color in zip(targets, colors):
                    self.assertEqual(native.getpixel(target), color)


if __name__ == "__main__":
    unittest.main()
