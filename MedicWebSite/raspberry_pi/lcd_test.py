#!/usr/bin/env python3
"""Standalone MSP2807 / ILI9341 SPI LCD test. No Flask, cameras, or LEDs.

Stop medilens-hardware before running: only one process may own the LCD.
QR/test mode initializes once, sends one complete frame, then only sleeps.
Keep the process running to retain GPIO ownership; Ctrl+C releases the pins.
Examples:
  sudo ./bin/python lcd_test.py --pattern test --rotation 90
  sudo ./bin/python lcd_test.py --url http://210.240.160.152:3001
  ./bin/python lcd_test.py --pattern test --preview-only
"""

import argparse
import hashlib
from pathlib import Path
import time

from PIL import Image, ImageDraw, ImageFont


# Native ILI9341 memory is 240x320. MV swaps axes for landscape.
# Rotation table: Adafruit_ILI9341::setRotation, BGR color order.
# https://github.com/adafruit/Adafruit_ILI9341/blob/master/Adafruit_ILI9341.cpp
ROTATIONS = {
    0: (0x48, 240, 320),
    90: (0x28, 320, 240),
    180: (0x88, 240, 320),
    270: (0xE8, 320, 240),
}


class ILI9341:
    def __init__(self, rotation=90, speed=8_000_000, rotation_mode="hardware"):
        madctl, self.width, self.height = ROTATIONS[rotation]
        if rotation_mode not in {"hardware", "software"}:
            raise ValueError("rotation_mode must be hardware or software")
        self.rotation = rotation
        self.rotation_mode = rotation_mode
        self.madctl = madctl if rotation_mode == "hardware" else 0x48
        self.memory_width, self.memory_height = ((self.width, self.height)
                                                if rotation_mode == "hardware" else (240, 320))
        self.speed = speed
        self.spi = self.dc = self.reset = None

    def open(self):
        import spidev
        from gpiozero import OutputDevice

        self.dc = OutputDevice(25, initial_value=False)
        self.reset = OutputDevice(24, initial_value=True)
        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)
        self.spi.max_speed_hz = self.speed
        self.spi.mode = 0
        self.spi.bits_per_word = 8
        print(f"[SPI] /dev/spidev0.0, {self.speed} Hz, mode 0, 8-bit; DC=GPIO25 RESET=GPIO24", flush=True)

    def command(self, value, values=b""):
        self.dc.off()
        self.spi.writebytes([value])
        if values:
            self.dc.on()
            self.spi.writebytes2(values)

    def initialize(self):
        print("[LCD] hardware reset", flush=True)
        self.reset.on()
        time.sleep(0.05)
        self.reset.off()
        time.sleep(0.05)
        self.reset.on()
        time.sleep(0.15)
        self.command(0x01)
        time.sleep(0.15)
        self.command(0x28)
        # Retain the power/gamma sequence from the supplied ILI9341 example.
        settings = (
            (0xCF, b"\x00\xc1\x30"),
            (0xED, b"\x64\x03\x12\x81"),
            (0xE8, b"\x85\x00\x78"),
            (0xCB, b"\x39\x2c\x00\x34\x02"),
            (0xF7, b"\x20"),
            (0xEA, b"\x00\x00"),
            (0xC0, b"\x23"),
            (0xC1, b"\x10"),
            (0xC5, b"\x3e\x28"),
            (0xC7, b"\x86"),
            (0x36, bytes([self.madctl])),
            (0x3A, b"\x55"),
            (0xB1, b"\x00\x18"),
            (0xB6, b"\x08\x82\x27"),
            (0xF2, b"\x00"),
            (0x26, b"\x01"),
            (0xE0, b"\x0f\x31\x2b\x0c\x0e\x08\x4e\xf1\x37\x07\x10\x03\x0e\x09\x00"),
            (0xE1, b"\x00\x0e\x14\x03\x11\x07\x31\xc1\x48\x08\x0f\x0c\x31\x36\x0f"),
        )
        for value, values in settings:
            self.command(value, values)
        self.command(0x11)
        time.sleep(0.12)
        self.command(0x29)
        time.sleep(0.1)
        print("[LCD] initialization commands sent (no hardware acknowledgement)", flush=True)

    def set_window(self, x0, y0, x1, y1):
        if not (0 <= x0 <= x1 < self.memory_width and 0 <= y0 <= y1 < self.memory_height):
            raise ValueError("Window outside current rotation's dimensions")
        self.command(0x2A, x0.to_bytes(2, "big") + x1.to_bytes(2, "big"))
        self.command(0x2B, y0.to_bytes(2, "big") + y1.to_bytes(2, "big"))
        self.command(0x2C)

    def to_memory_image(self, image):
        if image.size != (self.width, self.height):
            raise ValueError(f"Expected {self.width}x{self.height}, got {image.size}")
        image = image.convert("RGB")
        if self.rotation_mode == "software" and self.rotation:
            transpose = {90: Image.Transpose.ROTATE_90, 180: Image.Transpose.ROTATE_180,
                         270: Image.Transpose.ROTATE_270}
            image = image.transpose(transpose[self.rotation])
        if image.size != (self.memory_width, self.memory_height):
            raise ValueError("Rotated image does not match LCD memory window")
        return image

    def show_image(self, image):
        image = self.to_memory_image(image)
        pixels = image.load()
        width, height = self.memory_width, self.memory_height
        count = 0
        for y in range(height):
            row = bytearray(width * 2)
            for x in range(width):
                r, g, b = pixels[x, y]
                value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                row[2 * x] = value >> 8
                row[2 * x + 1] = value & 0xFF
            # No hard-coded 319: native and rotated windows must match MADCTL.
            self.set_window(0, y, width - 1, y)
            self.dc.on()
            self.spi.writebytes2(row)
            count += len(row)
        return count

    def clear(self):
        return self.show_image(Image.new("RGB", (self.width, self.height), "black"))

    def color_test(self, seconds=2):
        """No QR/font dependencies: each step must change the entire screen."""
        for color in ("black", "red", "lime", "blue", "white", "black"):
            print(f"[COLOR] sending full-screen {color}...", flush=True)
            count = self.show_image(Image.new("RGB", (self.width, self.height), color))
            print(f"[COLOR] {color}: sent {count} bytes; observe the physical LCD", flush=True)
            time.sleep(seconds)

    def close(self):
        print("[EXIT] releasing SPI/GPIO; RESET will no longer be actively held high", flush=True)
        for resource in (self.spi, self.dc, self.reset):
            if resource is not None:
                try:
                    resource.close()
                except Exception as error:
                    print(f"LCD close: {error}")


def create_screen(width, height, pattern, url, font_path):
    image = Image.new("RGB", (width, height), "black")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    # This border must touch all four edges with no noisy region beyond it.
    draw.rectangle((0, 0, width - 1, height - 1), outline="white", width=2)
    if pattern in {"test", "colors"}:
        colors = ("red", "lime", "blue", "white", "black", "yellow")
        for index, color in enumerate(colors):
            x0 = 2 + index * (width - 4) // len(colors)
            x1 = 1 + (index + 1) * (width - 4) // len(colors)
            draw.rectangle((x0, 30, x1, height - 31), fill=color)
        draw.text((width // 2, 8), f"ILI9341 {width} x {height}", fill="white", font=font, anchor="mt")
    else:
        import qrcode

        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=1, border=4)
        qr.add_data(url)
        qr.make(fit=True)
        code = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        scale = min(width - 24, height - 80) // code.width
        if scale < 1:
            raise ValueError("URL too long for this display")
        code = code.resize((code.width * scale, code.height * scale), Image.Resampling.NEAREST)
        image.paste(code, ((width - code.width) // 2, (height - code.height) // 2))
        try:
            title_font = ImageFont.truetype(font_path, 18)
            title = "掃描 QR Code 開始辨識"
        except OSError:
            title_font, title = font, "Scan QR Code"
        draw.text((width // 2, 8), title, fill="white", font=title_font, anchor="mt")
    # Orientation labels make mirroring/axis errors visible even on the QR page.
    for label, xy, anchor in (("TL", (4, 4), "lt"), ("TR", (width - 4, 4), "rt"),
                              ("BL", (4, height - 4), "lb"), ("BR", (width - 4, height - 4), "rb")):
        draw.text(xy, label, fill="white", font=font, anchor=anchor)
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rotation", type=int, choices=ROTATIONS, default=90)
    parser.add_argument("--rotation-mode", choices=("software", "hardware"), default="software",
                        help="software: keep LCD at native 240x320 and rotate pixels in Python")
    parser.add_argument("--speed", type=int, default=1_000_000, help="SPI clock in Hz (default: 1 MHz)")
    parser.add_argument("--pattern", choices=("qr", "test", "colors"), default="qr",
                        help="colors: cycle full-screen black/red/green/blue/white, then show border test")
    parser.add_argument("--url", default="http://210.240.160.152:3001")
    parser.add_argument("--font", default="/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
    parser.add_argument("--preview", type=Path, default=Path("lcd_preview.png"))
    parser.add_argument("--preview-only", action="store_true", help="Save PNG without accessing SPI/GPIO")
    parser.add_argument("--no-wait", action="store_true",
                        help="Release SPI/GPIO after sending; a floating RESET may blank the screen")
    args = parser.parse_args()
    if not 1 <= args.speed <= 8_000_000:
        parser.error("--speed must be between 1 and 8000000 Hz")
    lcd = ILI9341(args.rotation, args.speed, args.rotation_mode)
    source = Path(__file__).resolve()
    print(f"[FILE] {source}; SHA256={hashlib.sha256(source.read_bytes()).hexdigest()[:12]}", flush=True)
    print(f"[LCD] mode={args.rotation_mode}, rotation={args.rotation}, MADCTL=0x{lcd.madctl:02X}, "
          f"image={lcd.width}x{lcd.height}, memory={lcd.memory_width}x{lcd.memory_height}", flush=True)
    image = create_screen(lcd.width, lcd.height, args.pattern, args.url, args.font)
    image.save(args.preview)
    print(f"Preview: {args.preview.resolve()}", flush=True)
    if args.preview_only:
        return
    try:
        lcd.open()
        lcd.initialize()
        if args.pattern == "colors":
            lcd.color_test()
        count = lcd.show_image(image)
        print(f"Sent {count} bytes ({lcd.memory_width}x{lcd.memory_height} RGB565).", flush=True)
        print("Check the white border and TL/TR/BL/BR labels. Ctrl+C to exit.")
        if not args.no_wait:
            print("[HOLD] image sent; keeping GPIO objects alive, no more LCD commands", flush=True)
            while True:
                # Do not clear, redraw, reset, read GPIO, or reinitialize here.
                time.sleep(3600)
    except KeyboardInterrupt:
        print("LCD test stopped")
    except Exception as error:
        print(f"[ERROR] {type(error).__name__}: {error}", flush=True)
        raise
    finally:
        lcd.close()


if __name__ == "__main__":
    main()
