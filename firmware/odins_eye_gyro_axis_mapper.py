#!/usr/bin/env python3

import argparse
import time

from PIL import Image, ImageDraw, ImageFont

from pi_oled_test import HEIGHT, WIDTH, SSD1331


IMU_ADDR = 0x68
GYRO_SCALE = 131.0

OLED_SPI_BUS = 0
OLED_SPI_DEVICE = 0
OLED_DC = 25
OLED_RST = 24

AXES = [
    ("X axis", 0),
    ("Y axis", 1),
    ("Z axis", 2),
]


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--axis", choices=["x", "y", "z"], default="")
    return parser.parse_args()


def open_bus(bus_number: int = 1):
    try:
        from smbus2 import SMBus
    except ImportError:
        from smbus import SMBus
    return SMBus(bus_number)


def read_imu_gyro(bus):
    raw = bus.read_i2c_block_data(IMU_ADDR, 0x43, 6)
    values = []
    for index in range(0, 6, 2):
        value = (raw[index] << 8) | raw[index + 1]
        if value >= 0x8000:
            value -= 0x10000
        values.append(value)
    return values


def make_frame(title: str, lines: list[str], accent=(0, 180, 220), banner=(160, 30, 0)):
    image = Image.new("RGB", (WIDTH, HEIGHT), (5, 8, 18))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), outline=accent)
    draw.rectangle((4, 4, WIDTH - 5, 18), fill=banner)
    draw.text((8, 8), title[:14], font=font, fill=(255, 240, 200))

    y = 24
    for line in lines[:4]:
        draw.text((6, y), line[:18], font=font, fill=(220, 255, 230))
        y += 10
    return image


def show_frame(display, title: str, lines: list[str], accent=(0, 180, 220), banner=(160, 30, 0)):
    display.draw_image(make_frame(title, lines, accent=accent, banner=banner))


def run_axis_test(bus, display, axis_name: str, axis_index: int):
    bias_samples = []
    for _ in range(40):
        gyro = read_imu_gyro(bus)
        bias_samples.append(gyro[axis_index] / GYRO_SCALE)
        time.sleep(0.02)

    bias = sum(bias_samples) / len(bias_samples)
    angle = 0.0
    relative_angle = 0.0
    last_time = time.monotonic()

    show_frame(
        display,
        axis_name,
        ["Rotate now", "Same motion", "Watch result"],
        accent=(100, 220, 255),
        banner=(0, 100, 170),
    )
    print(f"{axis_name}: bias={bias:.2f} deg/s")

    end_time = time.monotonic() + 8.0
    while time.monotonic() < end_time:
        gyro = read_imu_gyro(bus)
        rate = (gyro[axis_index] / GYRO_SCALE) - bias
        now = time.monotonic()
        dt = now - last_time
        last_time = now
        angle += rate * dt
        relative_angle = angle

        show_frame(
            display,
            axis_name,
            [f"Delta {relative_angle:+.1f}", f"Rate {rate:+.1f}", "Rotate board"],
            accent=(100, 220, 255),
            banner=(0, 100, 170),
        )
        print(f"{axis_name}: delta={relative_angle:+.2f} rate={rate:+.2f}")
        time.sleep(0.06)

    show_frame(
        display,
        axis_name,
        [f"Final {relative_angle:+.1f}", "Next axis soon"],
        accent=(255, 180, 80),
        banner=(150, 70, 0),
    )
    print(f"{axis_name}: final delta={relative_angle:+.2f}")
    time.sleep(2.0)


def main() -> int:
    args = parse_args()
    display = SSD1331(
        spi_bus=OLED_SPI_BUS,
        spi_device=OLED_SPI_DEVICE,
        pin_dc=OLED_DC,
        pin_rst=OLED_RST,
    )
    display.open()
    try:
        with open_bus(1) as bus:
            axes = AXES
            if args.axis:
                axes = [item for item in AXES if item[0].lower().startswith(args.axis)]
            for axis_name, axis_index in axes:
                run_axis_test(bus, display, axis_name, axis_index)
    finally:
        display.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
