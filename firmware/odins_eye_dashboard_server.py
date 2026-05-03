#!/usr/bin/env python3

import argparse
import json
import mimetypes
from datetime import datetime
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "dashboard_assets"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Host the Odin's Eye capture dashboard on the Raspberry Pi."
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--captures-dir",
        default=str(Path.home() / "odins-eye-captures"),
        help="Directory containing capture JPEGs and JSON metadata.",
    )
    return parser.parse_args()


def iso_to_datetime(value: str | None):
    if not value:
        return None
    for fmt in ("%Y%m%d-%H%M%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def normalize_record(metadata_path: Path, captures_dir: Path):
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    image_path = payload.get("image_path")
    image_file = Path(image_path).name if image_path else metadata_path.with_suffix(".jpg").name
    image_full_path = captures_dir / image_file
    timestamp_raw = payload.get("timestamp") or metadata_path.stem.split("_")[0]
    timestamp_dt = iso_to_datetime(timestamp_raw)
    fallback_dt = datetime.fromtimestamp(metadata_path.stat().st_mtime)

    return {
        "timestamp": timestamp_raw,
        "timestamp_display": (
            timestamp_dt.strftime("%Y-%m-%d %H:%M:%S")
            if timestamp_dt else
            fallback_dt.strftime("%Y-%m-%d %H:%M:%S")
        ),
        "sort_key": timestamp_dt.timestamp() if timestamp_dt else metadata_path.stat().st_mtime,
        "speed_kmh": payload.get("speed_kmh"),
        "tilt_deg": payload.get("tilt_deg"),
        "aligned": payload.get("aligned"),
        "object_label": (
            payload.get("object_label")
            or payload.get("vehicle_label")
            or payload.get("label")
            or payload.get("object_type")
            or "Pending analysis"
        ),
        "license_plate": (
            payload.get("license_plate")
            or payload.get("plate_text")
            or payload.get("plate")
            or "Not available"
        ),
        "notes": payload.get("notes") or "Captured by Odin's Eye roadside monitor.",
        "metadata_file": metadata_path.name,
        "image_file": image_file,
        "image_url": f"/captures/{image_file}" if image_full_path.exists() else "",
    }


def load_records(captures_dir: Path):
    records = []

    if captures_dir.exists():
        for metadata_path in captures_dir.glob("*.json"):
            record = normalize_record(metadata_path, captures_dir)
            if record:
                records.append(record)

        # Fall back to bare JPEGs if metadata is not present yet.
        if not records:
            for image_path in captures_dir.glob("*.jpg"):
                records.append(
                    {
                        "timestamp": image_path.stem.split("_")[0],
                        "timestamp_display": datetime.fromtimestamp(image_path.stat().st_mtime).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                        "sort_key": image_path.stat().st_mtime,
                        "speed_kmh": None,
                        "tilt_deg": None,
                        "aligned": None,
                        "object_label": "Image only",
                        "license_plate": "Not available",
                        "notes": "No metadata JSON found for this capture yet.",
                        "metadata_file": "",
                        "image_file": image_path.name,
                        "image_url": f"/captures/{image_path.name}",
                    }
                )

    records.sort(key=lambda item: item["sort_key"], reverse=True)
    return records[:30]


def dashboard_stats(records):
    speeds = [record["speed_kmh"] for record in records if isinstance(record.get("speed_kmh"), (int, float))]
    return {
        "capture_count": len(records),
        "average_speed": round(sum(speeds) / len(speeds), 1) if speeds else None,
        "latest_timestamp": records[0]["timestamp_display"] if records else "No captures yet",
    }


def render_index_html():
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Odin's Eye Dashboard</title>
  <link rel="stylesheet" href="/static/odins_eye_dashboard.css">
</head>
<body>
  <div class="page-shell">
    <header class="hero">
      <div>
        <p class="eyebrow">Roadside Monitoring Console</p>
        <h1>Odin's Eye</h1>
        <p class="lede">Last 30 roadside captures, hosted directly by the Pi.</p>
      </div>
      <div class="hero-glow"></div>
    </header>

    <section class="stats" id="stats"></section>
    <section class="feed-header">
      <div>
        <h2>Recent Captures</h2>
        <p>Vehicle images, measured speed, plate data, and capture metadata.</p>
      </div>
    </section>
    <section class="capture-grid" id="capture-grid"></section>
  </div>
  <script src="/static/odins_eye_dashboard.js"></script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    captures_dir: Path = Path.home() / "odins-eye-captures"

    def _send_bytes(self, payload: bytes, content_type: str, status=HTTPStatus.OK):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, payload):
        self._send_bytes(json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

    def _serve_asset(self, asset_name: str):
        asset_path = ASSETS_DIR / asset_name
        if not asset_path.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        mime_type, _ = mimetypes.guess_type(asset_path.name)
        self._send_bytes(asset_path.read_bytes(), mime_type or "application/octet-stream")

    def _serve_capture_file(self, filename: str):
        safe_name = Path(filename).name
        capture_path = self.captures_dir / safe_name
        if not capture_path.exists() or not capture_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        mime_type, _ = mimetypes.guess_type(capture_path.name)
        self._send_bytes(capture_path.read_bytes(), mime_type or "application/octet-stream")

    def do_GET(self):
        parsed = urlparse(self.path)
        route = unquote(parsed.path)

        if route == "/":
            self._send_bytes(render_index_html().encode("utf-8"), "text/html; charset=utf-8")
            return

        if route == "/api/captures":
            records = load_records(self.captures_dir)
            self._send_json({"records": records, "stats": dashboard_stats(records)})
            return

        if route.startswith("/captures/"):
            self._serve_capture_file(route.replace("/captures/", "", 1))
            return

        if route == "/static/odins_eye_dashboard.css":
            self._serve_asset("odins_eye_dashboard.css")
            return

        if route == "/static/odins_eye_dashboard.js":
            self._serve_asset("odins_eye_dashboard.js")
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, fmt, *args):
        return


def main():
    args = parse_args()
    DashboardHandler.captures_dir = Path(args.captures_dir).expanduser().resolve()
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Odin's Eye dashboard serving on http://{args.host}:{args.port}")
    print(f"Captures directory: {DashboardHandler.captures_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
