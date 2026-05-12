#!/usr/bin/env python3

import argparse
import json
import math
import os
import subprocess
import time
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from odins_eye_oled_bringup import HEIGHT, WIDTH, SSD1331


ANGLE_DEG = 45.0
COS_TH = math.cos(math.radians(ANGLE_DEG))
SAMPLE_INTERVAL = 0.010
MIN_STRENGTH = 35
MIN_DEC_SEQ = 3
MIN_TRIGGER_DROP_M = 0.08
MAX_BURST_TIME = 0.25
MIN_CHANGE = 0.15
SPEED_RANGE = (0.1, 60.0)
SPEED_SCALE = 0.67
DROP_FIRST_BURST_SAMPLE = True

TF_LUNA_ADDR = 0x10
IMU_ADDR = 0x68
TARGET_ALIGN_DEG = -20.0
ALIGN_TOLERANCE_DEG = 2.0
GYRO_Z_SCALE = 131.0

OLED_SPI_BUS = 0
OLED_SPI_DEVICE = 0
OLED_DC = 25
OLED_RST = 24

RAW_LOG_PATH = os.path.expanduser("~/odins-eye-captures/raw_events.jsonl")
CAPTURES_DIR = os.path.expanduser("~/odins-eye-captures")
CAMERA_TIMEOUT_MS = 200
CAMERA_WIDTH = 2304
CAMERA_HEIGHT = 1296


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
    parser.add_argument(
        "--skip-calibration",
        action="store_true",
        help="Skip startup gyro calibration; assume relative-zero alignment.",
    )
    parser.add_argument(
        "--raw-log",
        default=RAW_LOG_PATH,
        help="Path to append per-event raw traces (JSON lines).",
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


def log_raw_event(path: str, event: dict) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="ascii") as handle:
            handle.write(json.dumps(event) + "\n")
    except OSError as exc:
        print(f"raw log write failed: {exc}")


def score_confidence(
    sample_count: int,
    fit_err_cm: float,
    burst_drop_m: float,
    distances: list[float],
) -> tuple[int, str]:
    sample_score = min(1.0, max(0.0, (sample_count - 6) / 8.0))
    err_score = min(1.0, max(0.0, 1.0 - (fit_err_cm / 30.0)))
    drop_score = min(1.0, max(0.0, (burst_drop_m - 0.10) / 1.40))

    if len(distances) >= 2:
        decreasing = sum(
            1 for a, b in zip(distances, distances[1:]) if b <= a
        )
        monotonicity = decreasing / (len(distances) - 1)
    else:
        monotonicity = 0.0
    monotonicity_score = monotonicity

    weighted = (
        (sample_score * 0.20)
        + (err_score * 0.35)
        + (drop_score * 0.25)
        + (monotonicity_score * 0.20)
    )
    confidence_pct = int(round(weighted * 100))

    if confidence_pct >= 70:
        label = "high"
    elif confidence_pct >= 45:
        label = "medium"
    else:
        label = "low"

    return confidence_pct, label


_active_capture_proc: subprocess.Popen | None = None


def _reap_active_capture() -> None:
    global _active_capture_proc
    proc = _active_capture_proc
    if proc is None:
        return
    if proc.poll() is None:
        print(f"killing stale capture pid={proc.pid}")
        proc.kill()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
    _active_capture_proc = None


def start_capture(stem: str):
    global _active_capture_proc
    _reap_active_capture()
    os.makedirs(CAPTURES_DIR, exist_ok=True)
    image_path = os.path.join(CAPTURES_DIR, f"{stem}.jpg")
    command = [
        "rpicam-still",
        "-n",
        "-o", image_path,
        "--timeout", str(CAMERA_TIMEOUT_MS),
        "--width", str(CAMERA_WIDTH),
        "--height", str(CAMERA_HEIGHT),
    ]
    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _active_capture_proc = proc
        return proc, image_path
    except (OSError, FileNotFoundError) as exc:
        print(f"camera launch failed: {exc}")
        return None, ""


def write_capture_metadata(stem: str, payload: dict) -> str:
    metadata_path = os.path.join(CAPTURES_DIR, f"{stem}.json")
    try:
        os.makedirs(CAPTURES_DIR, exist_ok=True)
        with open(metadata_path, "w", encoding="ascii") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        return metadata_path
    except OSError as exc:
        print(f"metadata write failed: {exc}")
        return ""


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
    buffer_s: list[int] = []
    dec_streak = 0
    last_r = None
    trigger_anchor_r = None
    capture_proc = None
    capture_path = ""
    capture_stem = ""
    t0 = 0.0
    printed_once = False
    sample_count = 0
    last_oled_update = 0.0
    event_seq = 0

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
            if args.skip_calibration:
                print("Skipping gyro calibration (--skip-calibration)")
                zero_deg = 0.0
            else:
                zero_deg = calibrate_imu(bus, display)
                if zero_deg is None:
                    print("Calibration not completed; proceeding with zero offset")
                    zero_deg = 0.0

            print("Starting live speed detector")
            print(
                f"angle={ANGLE_DEG}deg interval={SAMPLE_INTERVAL*1000:.1f}ms "
                f"strength>={MIN_STRENGTH}"
            )
            print(f"raw event log: {args.raw_log}")

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
                    buffer_s.clear()
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
                        buffer_s = [strength]
                        printed_once = False
                        capture_stem = datetime.now().strftime(
                            "%Y%m%d-%H%M%S-%f"
                        )
                        capture_proc, capture_path = start_capture(capture_stem)
                        print(
                            f"burst start distance_m={reading_m:.3f} strength={strength} "
                            f"drop={trigger_drop:.3f}"
                        )
                    elif state == "burst":
                        buffer_t.append(timestamp)
                        buffer_r.append(reading_m)
                        buffer_s.append(strength)
                        elapsed = timestamp - t0
                        should_stop = False

                        if len(buffer_r) >= 6:
                            recent = buffer_r[-6:]
                            if (recent[0] - recent[-1]) < MIN_CHANGE:
                                should_stop = True
                        if elapsed >= MAX_BURST_TIME:
                            should_stop = True

                        if should_stop and not printed_once:
                            event_seq += 1
                            reported_speed_kmh = None
                            fit_err_cm = None
                            reason = "insufficient_samples"

                            fit_t = buffer_t
                            fit_r = buffer_r
                            if DROP_FIRST_BURST_SAMPLE and len(buffer_r) >= 7:
                                fit_t = buffer_t[1:]
                                fit_r = buffer_r[1:]

                            if len(fit_r) >= 6:
                                slope, err = fit_line(fit_t, fit_r)
                                radial_speed = abs(slope)
                                true_speed = (radial_speed / COS_TH) * SPEED_SCALE
                                fit_err_cm = err * 100.0
                                reported_speed_kmh = true_speed * 3.6

                                if SPEED_RANGE[0] <= true_speed <= SPEED_RANGE[1]:
                                    reason = "accepted"
                                    burst_drop_m = (
                                        max(buffer_r) - min(buffer_r)
                                    )
                                    confidence_pct, confidence_label = score_confidence(
                                        sample_count=len(fit_r),
                                        fit_err_cm=fit_err_cm,
                                        burst_drop_m=burst_drop_m,
                                        distances=fit_r,
                                    )
                                    image_path = capture_path or ""
                                    if capture_proc is not None:
                                        try:
                                            capture_proc.wait(timeout=4)
                                        except subprocess.TimeoutExpired:
                                            capture_proc.kill()
                                            image_path = ""
                                    notes = (
                                        f"Confidence {confidence_pct}% "
                                        f"({confidence_label}). "
                                        f"Fit error {fit_err_cm:.1f} cm. "
                                        f"Range drop {burst_drop_m:.3f} m "
                                        f"across {len(fit_r)} samples."
                                    )
                                    write_capture_metadata(
                                        capture_stem,
                                        {
                                            "timestamp": capture_stem,
                                            "speed_kmh": round(reported_speed_kmh, 1),
                                            "tilt_deg": round(tilt_deg, 1),
                                            "aligned": abs(tilt_deg) <= 5.0,
                                            "object_label": "Pending analysis",
                                            "license_plate": "Not available",
                                            "notes": notes,
                                            "image_path": image_path,
                                            "confidence_pct": confidence_pct,
                                            "confidence_label": confidence_label,
                                            "fit_error_cm": round(fit_err_cm, 1),
                                            "burst_drop_m": round(burst_drop_m, 3),
                                            "sample_count": len(fit_r),
                                            "angle_deg": ANGLE_DEG,
                                            "speed_scale": SPEED_SCALE,
                                        },
                                    )
                                    print(
                                        f"Detected speed: {reported_speed_kmh:.1f} km/h "
                                        f"(fit error {fit_err_cm:.1f} cm, "
                                        f"samples={len(buffer_r)}, "
                                        f"confidence {confidence_pct}% {confidence_label})"
                                    )
                                    show_frame(
                                        display,
                                        "Detected",
                                        [
                                            f"{reported_speed_kmh:.1f} km/h",
                                            f"Err {fit_err_cm:.1f} cm",
                                            f"Conf {confidence_pct}%",
                                            f"Tilt {tilt_deg:+.1f} deg",
                                        ],
                                        accent=(255, 130, 120),
                                        banner=(180, 20, 20),
                                    )
                                    time.sleep(1.2)
                                else:
                                    reason = "speed_out_of_range"
                                    print(
                                        f"discarded burst: speed={reported_speed_kmh:.1f} km/h "
                                        f"outside range, samples={len(buffer_r)}"
                                    )

                            log_raw_event(
                                args.raw_log,
                                {
                                    "event_seq": event_seq,
                                    "wall_time": time.time(),
                                    "mono_time": t0,
                                    "reason": reason,
                                    "angle_deg": ANGLE_DEG,
                                    "cos_th": COS_TH,
                                    "speed_scale": SPEED_SCALE,
                                    "drop_first_burst_sample": DROP_FIRST_BURST_SAMPLE,
                                    "fit_sample_count": len(fit_r),
                                    "tilt_deg": round(tilt_deg, 2),
                                    "target_align_deg": TARGET_ALIGN_DEG,
                                    "reported_speed_kmh": (
                                        round(reported_speed_kmh, 2)
                                        if reported_speed_kmh is not None
                                        else None
                                    ),
                                    "fit_err_cm": (
                                        round(fit_err_cm, 2)
                                        if fit_err_cm is not None
                                        else None
                                    ),
                                    "sample_count": len(buffer_r),
                                    "times_s": [round(t - t0, 4) for t in buffer_t],
                                    "distances_m": [round(r, 3) for r in buffer_r],
                                    "strengths": list(buffer_s),
                                    "trigger_anchor_m": (
                                        round(trigger_anchor_r, 3)
                                        if trigger_anchor_r is not None
                                        else None
                                    ),
                                    "min_trigger_drop_m": MIN_TRIGGER_DROP_M,
                                    "min_strength": MIN_STRENGTH,
                                    "max_burst_time_s": MAX_BURST_TIME,
                                    "sample_interval_s": SAMPLE_INTERVAL,
                                },
                            )

                            printed_once = True
                            state = "idle"
                            buffer_t.clear()
                            buffer_r.clear()
                            buffer_s.clear()
                            dec_streak = 0
                            last_r = None
                            trigger_anchor_r = None
                            capture_proc = None
                            capture_path = ""
                            capture_stem = ""

                if args.samples and sample_count >= args.samples:
                    break

                time.sleep(SAMPLE_INTERVAL)
    finally:
        if display is not None:
            display.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
