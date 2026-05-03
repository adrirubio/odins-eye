#!/usr/bin/env python3

import argparse
import json
import shutil
import subprocess
from pathlib import Path


EXPECTED_I2C_DEVICES = {
    0x10: "TF-Luna",
    0x68: "MPU6050-compatible IMU",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Odin's Eye Pi-side hardware validation."
    )
    parser.add_argument("--bus", type=int, default=1, help="I2C bus number to scan.")
    parser.add_argument(
        "--capture",
        action="store_true",
        help="Capture a test image with rpicam-still.",
    )
    parser.add_argument(
        "--oled-test",
        action="store_true",
        help="Run the SPI OLED splash test after the checks.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path.home() / "odins-eye-hardware-check"),
        help="Directory for test artifacts.",
    )
    return parser.parse_args()


def open_bus(bus_number: int):
    try:
        from smbus2 import SMBus
    except ImportError:
        from smbus import SMBus
    return SMBus(bus_number)


def scan_i2c_bus(bus_number: int) -> dict:
    found = {}
    with open_bus(bus_number) as bus:
        for address in range(0x03, 0x78):
            try:
                bus.read_byte(address)
            except OSError:
                continue
            found[address] = EXPECTED_I2C_DEVICES.get(address, "Unknown device")
    return found


def read_tfluna_sample(bus_number: int) -> dict:
    with open_bus(bus_number) as bus:
        data = bus.read_i2c_block_data(0x10, 0x00, 6)

    distance_cm = data[0] | (data[1] << 8)
    flux = data[2] | (data[3] << 8)
    temperature_c = ((data[4] | (data[5] << 8)) / 8.0) - 256.0
    return {
        "distance_cm": distance_cm,
        "flux": flux,
        "temperature_c": round(temperature_c, 2),
        "raw_bytes": data,
    }


def read_imu_sample(bus_number: int) -> dict:
    with open_bus(bus_number) as bus:
        who_am_i = bus.read_byte_data(0x68, 0x75)
        accel = bus.read_i2c_block_data(0x68, 0x3B, 6)

    ax_raw = (accel[0] << 8) | accel[1]
    ay_raw = (accel[2] << 8) | accel[3]
    az_raw = (accel[4] << 8) | accel[5]

    if ax_raw >= 0x8000:
        ax_raw -= 0x10000
    if ay_raw >= 0x8000:
        ay_raw -= 0x10000
    if az_raw >= 0x8000:
        az_raw -= 0x10000

    return {
        "who_am_i": who_am_i,
        "who_am_i_hex": f"0x{who_am_i:02X}",
        "accel_raw": {
            "x": ax_raw,
            "y": ay_raw,
            "z": az_raw,
        },
    }


def list_cameras() -> str:
    command = shutil.which("rpicam-still")
    if not command:
        return "rpicam-still not installed"
    result = subprocess.run(
        [command, "--list-cameras"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def capture_test_image(output_dir: Path) -> str:
    command = shutil.which("rpicam-still")
    if not command:
        raise RuntimeError("rpicam-still not installed")

    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / "camera-test.jpg"

    subprocess.run(
        [command, "-n", "-o", str(image_path), "--timeout", "1000"],
        check=True,
    )
    return str(image_path)


def run_oled_test() -> str:
    script = Path(__file__).with_name("pi_oled_test.py")
    subprocess.run(["python3", str(script), "--once"], check=True)
    return str(script)


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    results = {
        "i2c_bus": args.bus,
        "i2c_devices": {},
        "spi_devices": [str(path) for path in sorted(Path("/dev").glob("spidev*"))],
        "camera_list": list_cameras(),
    }

    found_devices = scan_i2c_bus(args.bus)
    results["i2c_devices"] = {
        f"0x{address:02X}": name for address, name in found_devices.items()
    }

    if 0x10 in found_devices:
        results["tfluna"] = read_tfluna_sample(args.bus)

    if 0x68 in found_devices:
        results["imu"] = read_imu_sample(args.bus)

    if args.capture:
        results["test_image"] = capture_test_image(output_dir)

    if args.oled_test:
        results["oled_test_script"] = run_oled_test()

    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
