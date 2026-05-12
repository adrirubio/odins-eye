#!/usr/bin/env python3

import argparse
import time

import RPi.GPIO as GPIO
import spidev
from PIL import Image, ImageDraw, ImageFont


WIDTH = 96
HEIGHT = 64
SPI_MAX_SPEED_HZ = 16_000_000


class SSD1331:
    def __init__(self, spi_bus: int, spi_device: int, pin_dc: int, pin_rst: int) -> None:
        self.spi = spidev.SpiDev()
        self.spi_bus = spi_bus
        self.spi_device = spi_device
        self.pin_dc = pin_dc
        self.pin_rst = pin_rst

    def open(self) -> None:
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.pin_dc, GPIO.OUT)
        GPIO.setup(self.pin_rst, GPIO.OUT)

        self.spi.open(self.spi_bus, self.spi_device)
        self.spi.max_speed_hz = SPI_MAX_SPEED_HZ
        self.spi.mode = 0

        GPIO.output(self.pin_rst, GPIO.HIGH)
        time.sleep(0.05)
        GPIO.output(self.pin_rst, GPIO.LOW)
        time.sleep(0.05)
        GPIO.output(self.pin_rst, GPIO.HIGH)
        time.sleep(0.05)

        self._init_display()

    def close(self) -> None:
        self.spi.close()
        GPIO.cleanup([self.pin_dc, self.pin_rst])

    def command(self, *values: int) -> None:
        GPIO.output(self.pin_dc, GPIO.LOW)
        self.spi.xfer2(list(values))

    def data(self, values) -> None:
        GPIO.output(self.pin_dc, GPIO.HIGH)
        values = list(values)
        chunk_size = 4096
        for offset in range(0, len(values), chunk_size):
            self.spi.xfer2(values[offset:offset + chunk_size])

    def _init_display(self) -> None:
        self.command(0xAE)
        self.command(0xA0, 0x72)
        self.command(0xA1, 0x00)
        self.command(0xA2, 0x00)
        self.command(0xA4)
        self.command(0xA8, 0x3F)
        self.command(0xAD, 0x8E)
        self.command(0xB0, 0x0B)
        self.command(0xB1, 0x31)
        self.command(0xB3, 0xF0)
        self.command(0x8A, 0x64)
        self.command(0x8B, 0x78)
        self.command(0x8C, 0x64)
        self.command(0xBB, 0x3A)
        self.command(0xBE, 0x3E)
        self.command(0x87, 0x0F)
        self.command(0x81, 0x91)
        self.command(0x82, 0x50)
        self.command(0x83, 0x7D)
        self.command(0xAF)
        self.clear()

    def clear(self) -> None:
        self.command(0x25, 0x00, 0x00, WIDTH - 1, HEIGHT - 1)

    def draw_image(self, image: Image.Image) -> None:
        image = image.convert("RGB").resize((WIDTH, HEIGHT))

        self.command(0x15, 0x00, WIDTH - 1)
        self.command(0x75, 0x00, HEIGHT - 1)
        self.command(0x5C)

        payload = []
        for red, green, blue in image.getdata():
            payload.append(red & 0xF8)
            payload.append(((green >> 5) << 5) | (blue >> 3))

        self.data(payload)


def render_demo_frame() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), (5, 8, 18))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), outline=(0, 180, 220))
    draw.rectangle((4, 4, WIDTH - 5, 24), fill=(160, 30, 0))
    draw.text((8, 10), "Odin's Eye", font=font, fill=(255, 230, 180))
    draw.text((8, 32), "SPI OLED TEST", font=font, fill=(130, 255, 140))
    draw.text((8, 46), "SSD1331", font=font, fill=(255, 255, 255))
    return image


def render_color_frame(color) -> Image.Image:
    return Image.new("RGB", (WIDTH, HEIGHT), color)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SSD1331 SPI OLED bring-up test.")
    parser.add_argument("--spi-bus", type=int, default=0)
    parser.add_argument("--spi-device", type=int, default=1)
    parser.add_argument("--dc", type=int, default=24)
    parser.add_argument("--rst", type=int, default=25)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Draw one frame and exit.",
    )
    parser.add_argument(
        "--hold-seconds",
        type=float,
        default=5.0,
        help="How long to keep the image visible when not using --once.",
    )
    parser.add_argument(
        "--pattern",
        choices=["demo", "red", "green", "blue", "white"],
        default="demo",
        help="Test pattern to draw.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    display = SSD1331(
        spi_bus=args.spi_bus,
        spi_device=args.spi_device,
        pin_dc=args.dc,
        pin_rst=args.rst,
    )
    display.open()
    try:
        if args.pattern == "demo":
            frame = render_demo_frame()
        elif args.pattern == "red":
            frame = render_color_frame((255, 0, 0))
        elif args.pattern == "green":
            frame = render_color_frame((0, 255, 0))
        elif args.pattern == "blue":
            frame = render_color_frame((0, 0, 255))
        else:
            frame = render_color_frame((255, 255, 255))
        display.draw_image(frame)
        if not args.once:
            time.sleep(args.hold_seconds)
    finally:
        display.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
