#!/usr/bin/env python3
"""Odins Eye - Module Test Script
Reads gyroscope roll angle, displays on SPI OLED, and takes a test photo.

PCB Pin Mapping:
  OLED (SPI): CS=GPIO8(CE0), DC=GPIO24, RST=GPIO25, SCK=GPIO11, MOSI=GPIO10
  Gyroscope:  I2C bus 1, address 0x68 (MPU6050)
  Camera:     Pi Camera 3 (imx708) via CSI
"""

import time
import math
import struct
import subprocess
import spidev
import lgpio
import smbus2
from PIL import Image, ImageDraw, ImageFont

# --- Pin definitions ---
DC_PIN = 24
RST_PIN = 25

# --- MPU6050 registers ---
MPU_ADDR = 0x68
PWR_MGMT_1 = 0x6B
ACCEL_XOUT_H = 0x3B

# --- SSD1306 commands ---
SSD1306_DISPLAYOFF = 0xAE
SSD1306_DISPLAYON = 0xAF
SSD1306_SETDISPLAYCLOCKDIV = 0xD5
SSD1306_SETMULTIPLEX = 0xA8
SSD1306_SETDISPLAYOFFSET = 0xD3
SSD1306_SETSTARTLINE = 0x40
SSD1306_CHARGEPUMP = 0x8D
SSD1306_MEMORYMODE = 0x20
SSD1306_SEGREMAP = 0xA1
SSD1306_COMSCANDEC = 0xC8
SSD1306_SETCOMPINS = 0xDA
SSD1306_SETCONTRAST = 0x81
SSD1306_SETPRECHARGE = 0xD9
SSD1306_SETVCOMDETECT = 0xDB
SSD1306_NORMALDISPLAY = 0xA6
SSD1306_DISPLAYALLON_RESUME = 0xA4
SSD1306_COLUMNADDR = 0x21
SSD1306_PAGEADDR = 0x22

WIDTH = 128
HEIGHT = 64


class SSD1306_SPI:
    def __init__(self, gpio_handle, spi_bus=0, spi_device=0):
        self.h = gpio_handle
        lgpio.gpio_claim_output(self.h, DC_PIN)
        lgpio.gpio_claim_output(self.h, RST_PIN)

        self.spi = spidev.SpiDev()
        self.spi.open(spi_bus, spi_device)
        self.spi.max_speed_hz = 8000000
        self.spi.mode = 0

        self._reset()
        self._init_display()

    def _reset(self):
        lgpio.gpio_write(self.h, RST_PIN, 1)
        time.sleep(0.001)
        lgpio.gpio_write(self.h, RST_PIN, 0)
        time.sleep(0.01)
        lgpio.gpio_write(self.h, RST_PIN, 1)
        time.sleep(0.001)

    def _command(self, *cmds):
        lgpio.gpio_write(self.h, DC_PIN, 0)
        self.spi.writebytes2(list(cmds))

    def _data(self, data):
        lgpio.gpio_write(self.h, DC_PIN, 1)
        self.spi.writebytes2(data)

    def _init_display(self):
        self._command(
            SSD1306_DISPLAYOFF,
            SSD1306_SETDISPLAYCLOCKDIV, 0x80,
            SSD1306_SETMULTIPLEX, HEIGHT - 1,
            SSD1306_SETDISPLAYOFFSET, 0x00,
            SSD1306_SETSTARTLINE,
            SSD1306_CHARGEPUMP, 0x14,
            SSD1306_MEMORYMODE, 0x00,
            SSD1306_SEGREMAP,
            SSD1306_COMSCANDEC,
            SSD1306_SETCOMPINS, 0x12,
            SSD1306_SETCONTRAST, 0xCF,
            SSD1306_SETPRECHARGE, 0xF1,
            SSD1306_SETVCOMDETECT, 0x40,
            SSD1306_DISPLAYALLON_RESUME,
            SSD1306_NORMALDISPLAY,
            SSD1306_DISPLAYON,
        )

    def display(self, image):
        self._command(SSD1306_COLUMNADDR, 0, WIDTH - 1)
        self._command(SSD1306_PAGEADDR, 0, (HEIGHT // 8) - 1)
        buf = self._image_to_buffer(image)
        self._data(buf)

    def _image_to_buffer(self, image):
        pixels = list(image.getdata())
        buf = [0] * (WIDTH * HEIGHT // 8)
        for y in range(HEIGHT):
            for x in range(WIDTH):
                if pixels[y * WIDTH + x]:
                    buf[x + (y // 8) * WIDTH] |= 1 << (y % 8)
        return buf

    def clear(self):
        self._command(SSD1306_COLUMNADDR, 0, WIDTH - 1)
        self._command(SSD1306_PAGEADDR, 0, (HEIGHT // 8) - 1)
        self._data([0] * (WIDTH * HEIGHT // 8))

    def close(self):
        self.clear()
        self._command(SSD1306_DISPLAYOFF)
        self.spi.close()


# --- Gyroscope helpers ---
def init_mpu(bus):
    bus.write_byte_data(MPU_ADDR, PWR_MGMT_1, 0x00)
    time.sleep(0.1)

def read_accel(bus):
    data = bus.read_i2c_block_data(MPU_ADDR, ACCEL_XOUT_H, 6)
    ax = struct.unpack('>h', bytes(data[0:2]))[0] / 16384.0
    ay = struct.unpack('>h', bytes(data[2:4]))[0] / 16384.0
    az = struct.unpack('>h', bytes(data[4:6]))[0] / 16384.0
    return ax, ay, az

def roll_from_accel(ax, ay, az):
    return math.degrees(math.atan2(ay, math.sqrt(ax * ax + az * az)))


# --- Init hardware ---
# Free GPIOs if stuck from a previous crash
h = lgpio.gpiochip_open(0)
try:
    lgpio.gpio_free(h, DC_PIN)
except lgpio.error:
    pass
try:
    lgpio.gpio_free(h, RST_PIN)
except lgpio.error:
    pass
lgpio.gpiochip_close(h)
h = lgpio.gpiochip_open(0)
oled = SSD1306_SPI(h)
bus = smbus2.SMBus(1)
init_mpu(bus)

# Calibrate: current position = 0 degrees
print("Calibrating gyroscope (keep PCB still)...")
samples = [roll_from_accel(*read_accel(bus)) for _ in range(50)]
offset = sum(samples) / len(samples)
print(f"Zero offset: {offset:.2f}°")

locked = False
photo_taken = False

try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
    font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
except OSError:
    font = ImageFont.load_default()
    font_small = font

print("Running... tilt PCB right to 20° to lock. Ctrl+C to exit.")

try:
    while True:
        ax, ay, az = read_accel(bus)
        angle = roll_from_accel(ax, ay, az) - offset

        img = Image.new("1", (WIDTH, HEIGHT), 0)
        draw = ImageDraw.Draw(img)

        draw.text((0, 0), "Odins Eye", font=font, fill=1)

        if abs(angle) >= 20.0 and not locked:
            locked = True
            lock_angle = angle
            print(f"LOCKED at {lock_angle:.1f}°")

            # Take test photo
            print("Taking test photo...")
            subprocess.run([
                "rpicam-still", "-o", "/home/adrian/test_photo.jpg",
                "--width", "2304", "--height", "1296",
                "-t", "1000", "--nopreview"
            ], check=True)
            photo_taken = True
            print("Photo saved to /home/adrian/test_photo.jpg")

        if locked:
            draw.text((0, 20), "POSITION LOCKED", font=font, fill=1)
            draw.text((0, 40), f"Angle: {lock_angle:.1f} deg", font=font_small, fill=1)
            if photo_taken:
                draw.text((0, 52), "Photo captured!", font=font_small, fill=1)
        else:
            draw.text((0, 22), f"Roll: {angle:.1f} deg", font=font, fill=1)
            bar_width = min(int(abs(angle) / 20.0 * 100), 100)
            draw.rectangle((14, 45, 114, 55), outline=1)
            if bar_width > 0:
                draw.rectangle((14, 45, 14 + bar_width, 55), fill=1)
            draw.text((0, 45), "0", font=font_small, fill=1)
            draw.text((116, 45), "20", font=font_small, fill=1)

        oled.display(img)
        time.sleep(0.05)

except KeyboardInterrupt:
    print("\nExiting.")
finally:
    oled.close()
    lgpio.gpiochip_close(h)
    bus.close()
