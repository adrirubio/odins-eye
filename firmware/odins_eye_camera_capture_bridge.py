#!/usr/bin/env python3

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime


CAPTURE_PATTERN = re.compile(
    r"CAPTURE\s+speed_kmh=(?P<speed>[0-9]+(?:\.[0-9]+)?)\s+"
    r"tilt_deg=(?P<tilt>-?[0-9]+(?:\.[0-9]+)?)\s+"
    r"aligned=(?P<aligned>[01])"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Listen for Odin's Eye firmware capture events and trigger the Pi camera."
    )
    parser.add_argument("--port", help="Serial port from the firmware, for example /dev/ttyACM0.")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate.")
    parser.add_argument(
        "--images-dir",
        default=os.path.expanduser("~/odins-eye-captures"),
        help="Directory where JPEGs and metadata should be stored.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=1200,
        help="Camera warmup/capture time passed to rpicam-still.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=2304,
        help="Requested capture width.",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=1296,
        help="Requested capture height.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be captured without invoking the camera.",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read firmware lines from stdin instead of a serial device.",
    )
    return parser.parse_args()


def require_serial():
    try:
        import serial
    except ImportError as exc:
        raise SystemExit(
            "pyserial is required for --port mode. Install it with `pip install pyserial`."
        ) from exc
    return serial


def capture_image(args: argparse.Namespace, event: dict) -> None:
    os.makedirs(args.images_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = (
        f"{timestamp}_speed-{event['speed_kmh']:.1f}_"
        f"tilt-{event['tilt_deg']:.1f}_aligned-{event['aligned']}"
    )
    image_path = os.path.join(args.images_dir, f"{stem}.jpg")
    metadata_path = os.path.join(args.images_dir, f"{stem}.json")

    command = [
        "rpicam-still",
        "-n",
        "-o",
        image_path,
        "--timeout",
        str(args.timeout_ms),
        "--width",
        str(args.width),
        "--height",
        str(args.height),
    ]

    print(f"[capture] speed={event['speed_kmh']:.1f} km/h tilt={event['tilt_deg']:.1f} deg")
    if args.dry_run:
        print("[capture] dry-run:", " ".join(command))
    else:
        subprocess.run(command, check=True)

    with open(metadata_path, "w", encoding="ascii") as handle:
        json.dump(
            {
                "timestamp": timestamp,
                "speed_kmh": event["speed_kmh"],
                "tilt_deg": event["tilt_deg"],
                "aligned": bool(event["aligned"]),
                "image_path": image_path,
            },
            handle,
            indent=2,
        )
        handle.write("\n")

    print(f"[capture] wrote {metadata_path}")


def parse_capture_line(line: str):
    match = CAPTURE_PATTERN.search(line.strip())
    if not match:
        return None

    return {
        "speed_kmh": float(match.group("speed")),
        "tilt_deg": float(match.group("tilt")),
        "aligned": int(match.group("aligned")),
    }


def read_lines_from_stdin():
    for line in sys.stdin:
        yield line


def read_lines_from_serial(port: str, baud: int):
    serial = require_serial()
    with serial.Serial(port, baudrate=baud, timeout=1) as handle:
        while True:
            raw = handle.readline()
            if not raw:
                continue
            yield raw.decode("utf-8", errors="replace")


def main() -> int:
    args = parse_args()
    if not args.stdin and not args.port:
        raise SystemExit("Pass either --stdin or --port.")

    line_source = read_lines_from_stdin() if args.stdin else read_lines_from_serial(args.port, args.baud)

    for line in line_source:
        event = parse_capture_line(line)
        if event is None:
            print(line.rstrip())
            continue

        capture_image(args, event)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
