#!/usr/bin/env python3

import argparse
import math
import time

from PIL import Image, ImageDraw, ImageFont

from pi_oled_test import HEIGHT, WIDTH, SSD1331


ANGLE_DEG = 45.0
COS_TH = math.cos(math.radians(ANGLE_DEG))
SAMPLE_INTERVAL = 0.005
MIN_STRENGTH = 35
MIN_DEC_SEQ = 3
MIN_TRIGGER_DROP_M = 0.08
MAX_BURST_TIME = 0.25
MIN_CHANGE = 0.5
SPEED_RANGE = (0.1, 60.0)

TF_LUNA_ADDR = 0x10
IMU_ADDR = 0x68
TARGET_ALIGN_DEG = -20.0
ALIGN_TOLERANCE_DEG = 2.0
GYRO_Z_SCALE = 131.0

OLED_SPI_BUS = 0
OLED_SPI_DEVICE = 0
OLED_DC = 25
OLED_RST = 24


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Live Pi-side speed detection using the repo's TF-Luna algorithm."
    )
    parser.add_argument("--bus", type=int, default=1, help="I2C bus number.")
    parser.add_argument(
        "--samples",
        type=int,
        default=0,
        help="Optional number of samples to read before exiting. 0 means run forever.",
    )
    parser.add_argument(
        "--show-raw",
        action="store_true",
        help="Print each raw sample while monitoring.",
    )
    parser.add_argument(
        "--skip-oled",
        action="store_true",
        help="Run without the OLED UI.",
    )
    return parser.parse_args()


def open_bus(bus_number: int):
    try:
        from smbus2 import SMBus
    except ImportError:
        from smbus import SMBus
    return SMBus(bus_number)


def read_tfluna_sample(bus) -> tuple[float, int]:
    data = bus.read_i2c_block_data(TF_LUNA_ADDR, 0x00, 6)
    distance_cm = data[0] | (data[1] << 8)
    flux = data[2] | (data[3] << 8)
    return distance_cm / 100.0, flux


def read_imu_accel(bus) -> tuple[int, int, int]:
    raw = bus.read_i2c_block_data(IMU_ADDR, 0x3B, 6)
    values = []
    for index in range(0, 6, 2):
        value = (raw[index] << 8) | raw[index + 1]
        if value >= 0x8000:
            value -= 0x10000
        values.append(value)
    return values[0], values[1], values[2]


def read_imu_gyro(bus) -> tuple[int, int, int]:
    raw = bus.read_i2c_block_data(IMU_ADDR, 0x43, 6)
    values = []
    for index in range(0, 6, 2):
        value = (raw[index] << 8) | raw[index + 1]
        if value >= 0x8000:
            value -= 0x10000
        values.append(value)
    return values[0], values[1], values[2]


def compute_tilt_deg(ax: int, ay: int, az: int) -> float:
    return math.degrees(math.atan2(ax, math.sqrt((ay * ay) + (az * az))))


def fit_line(timestamps: list[float], readings: list[float]) -> tuple[float, float]:
    n = len(timestamps)
    centered_t = [t - (sum(timestamps) / n) for t in timestamps]
    mean_r = sum(readings) / n

    numerator = sum(t * (r - mean_r) for t, r in zip(centered_t, readings))
    denominator = sum(t * t for t in centered_t)
    slope = numerator / denominator if denominator else 0.0
    intercept = mean_r

    squared_error = 0.0
    for t, r in zip(centered_t, readings):
        predicted = (slope * t) + intercept
        squared_error += (r - predicted) ** 2
    err = math.sqrt(squared_error / n)
    return slope, err


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
    if display is None:
        return
    display.draw_image(make_frame(title, lines, accent=accent, banner=banner))


def calibrate_imu(bus, display):
    print("Starting gyroscope calibration")
    show_frame(
        display,
        "Gyro Cal",
        ["Gyroscope", "calibration...", "Hold still"],
        accent=(255, 190, 60),
        banner=(180, 80, 0),
    )

    bias_samples = []
    for _ in range(40):
        _, gy_raw, _ = read_imu_gyro(bus)
        bias_samples.append(gy_raw / GYRO_Z_SCALE)
        time.sleep(0.02)

    gyro_bias_dps = sum(bias_samples) / len(bias_samples)
    print(f"Gyro bias: {gyro_bias_dps:.2f} deg/s")

    show_frame(
        display,
        "Aim Road",
        ["Rotate right", f"to {TARGET_ALIGN_DEG:.0f} deg", "Smooth motion"],
        accent=(80, 220, 255),
        banner=(0, 90, 160),
    )
    time.sleep(0.8)

    deadline = time.monotonic() + 12.0
    relative_yaw_deg = 0.0
    last_time = time.monotonic()
    aligned_once = False
    while True:
        _, gy_raw, _ = read_imu_gyro(bus)
        now = time.monotonic()
        dt = now - last_time
        last_time = now

        gy_dps = (gy_raw / GYRO_Z_SCALE) - gyro_bias_dps
        relative_yaw_deg += gy_dps * dt
        delta = TARGET_ALIGN_DEG - relative_yaw_deg

        if abs(delta) <= ALIGN_TOLERANCE_DEG:
            aligned_once = True

        direction = "turn right" if delta > 0 else "turn left"
        show_frame(
            display,
            "Aim Road",
            [
                f"Yaw {relative_yaw_deg:+.1f} deg",
                f"Target {TARGET_ALIGN_DEG:+.0f} deg",
                direction,
                f"delta {delta:+.1f}",
            ],
            accent=(80, 220, 255),
            banner=(0, 90, 160),
        )
        print(
            f"Calibration guide: yaw={relative_yaw_deg:+.1f} deg "
            f"target={TARGET_ALIGN_DEG:+.1f} deg {direction}"
        )
        if time.monotonic() > deadline:
            break
        time.sleep(0.08)

    if abs(TARGET_ALIGN_DEG - relative_yaw_deg) > ALIGN_TOLERANCE_DEG:
        show_frame(
            display,
            "Not Aligned",
            [f"Yaw {relative_yaw_deg:+.1f} deg", "Try again", "Need -20 deg"],
            accent=(255, 120, 120),
            banner=(160, 30, 30),
        )
        print(
            "Alignment timeout"
            if not aligned_once else
            f"Alignment ended out of range at {relative_yaw_deg:+.1f} deg"
        )
        time.sleep(1.5)
        return None

    show_frame(
        display,
        "Calibrated",
        ["Calibrated", f"Yaw {relative_yaw_deg:+.1f} deg", "Speed mode live"],
        accent=(120, 255, 150),
        banner=(0, 130, 40),
    )
    print(f"Calibrated. Relative yaw={relative_yaw_deg:+.1f} deg")
    time.sleep(1.5)
    return 0.0


def main() -> int:
    args = parse_args()

    state = "idle"
    buffer_t: list[float] = []
    buffer_r: list[float] = []
    dec_streak = 0
    last_r = None
    trigger_anchor_r = None
    t0 = 0.0
    printed_once = False
    sample_count = 0
    last_oled_update = 0.0

    display = None
    if not args.skip_oled:
        display = SSD1331(
            spi_bus=OLED_SPI_BUS,
            spi_device=OLED_SPI_DEVICE,
            pin_dc=OLED_DC,
            pin_rst=OLED_RST,
        )
        display.open()

    try:
        with open_bus(args.bus) as bus:
            zero_deg = calibrate_imu(bus, display)
            if zero_deg is None:
                return 1

            print("Starting live speed detector")
            print(
                f"angle={ANGLE_DEG}deg interval={SAMPLE_INTERVAL*1000:.1f}ms "
                f"strength>={MIN_STRENGTH}"
            )

            while True:
                sample_count += 1
                timestamp = time.monotonic()

                try:
                    reading_m, strength = read_tfluna_sample(bus)
                    ax, ay, az = read_imu_accel(bus)
                except OSError as exc:
                    print(f"read error: {exc}")
                    time.sleep(SAMPLE_INTERVAL)
                    continue

                tilt_deg = compute_tilt_deg(ax, ay, az) - zero_deg

                if args.show_raw:
                    print(
                        f"raw distance_m={reading_m:.3f} strength={strength} "
                        f"tilt={tilt_deg:+.1f}"
                    )

                if display is not None and (timestamp - last_oled_update) > 0.12:
                    show_frame(
                        display,
                        "Odin's Eye",
                        [
                            f"Tilt {tilt_deg:+.1f} deg",
                            f"Road {TARGET_ALIGN_DEG:.0f} deg",
                            f"Dist {reading_m:.2f} m",
                            f"Flux {strength}",
                        ],
                    )
                    last_oled_update = timestamp

                if strength < MIN_STRENGTH or reading_m <= 0:
                    state = "idle"
                    buffer_t.clear()
                    buffer_r.clear()
                    dec_streak = 0
                    last_r = None
                    trigger_anchor_r = None
                    printed_once = False
                else:
                    if last_r is None:
                        trigger_anchor_r = reading_m

                    if last_r is not None and reading_m < last_r:
                        dec_streak += 1
                    else:
                        dec_streak = 0
                        trigger_anchor_r = reading_m
                    last_r = reading_m

                    trigger_drop = 0.0
                    if trigger_anchor_r is not None:
                        trigger_drop = max(0.0, trigger_anchor_r - reading_m)

                    if (
                        state == "idle"
                        and dec_streak >= MIN_DEC_SEQ
                        and trigger_drop >= MIN_TRIGGER_DROP_M
                    ):
                        state = "burst"
                        t0 = timestamp
                        buffer_t = [timestamp]
                        buffer_r = [reading_m]
                        printed_once = False
                        print(
                            f"burst start distance_m={reading_m:.3f} strength={strength} "
                            f"drop={trigger_drop:.3f}"
                        )
                    elif state == "burst":
                        buffer_t.append(timestamp)
                        buffer_r.append(reading_m)
                        elapsed = timestamp - t0
                        should_stop = False

                        if len(buffer_r) >= 6:
                            recent = buffer_r[-6:]
                            if (recent[0] - recent[-1]) < MIN_CHANGE:
                                should_stop = True
                        if elapsed >= MAX_BURST_TIME:
                            should_stop = True

                        if should_stop and not printed_once:
                            if len(buffer_r) >= 6:
                                slope, err = fit_line(buffer_t, buffer_r)
                                radial_speed = abs(slope)
                                true_speed = radial_speed / COS_TH
                                if SPEED_RANGE[0] <= true_speed <= SPEED_RANGE[1]:
                                    speed_kmh = true_speed * 3.6
                                    print(
                                        f"Detected speed: {speed_kmh:.1f} km/h "
                                        f"(fit error {err * 100:.1f} cm, "
                                        f"samples={len(buffer_r)})"
                                    )
                                    show_frame(
                                        display,
                                        "Detected",
                                        [
                                            f"{speed_kmh:.1f} km/h",
                                            f"Err {err*100:.1f} cm",
                                            f"Tilt {tilt_deg:+.1f} deg",
                                            "Tracking locked",
                                        ],
                                        accent=(255, 130, 120),
                                        banner=(180, 20, 20),
                                    )
                                    time.sleep(1.2)
                                else:
                                    print(
                                        f"discarded burst: speed={true_speed * 3.6:.1f} km/h "
                                        f"outside range, samples={len(buffer_r)}"
                                    )
                            printed_once = True
                            state = "idle"
                            buffer_t.clear()
                            buffer_r.clear()
                            dec_streak = 0
                            last_r = None
                            trigger_anchor_r = None

                if args.samples and sample_count >= args.samples:
                    break

                time.sleep(SAMPLE_INTERVAL)
    finally:
        if display is not None:
            display.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
