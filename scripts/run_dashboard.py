#!/usr/bin/env python3
"""
scripts/run_dashboard.py — ASG-RAOP Interactive Operator Cockpit Server
========================================================================
Zero-dependency HTTP and REST API server powering the Operator Web Cockpit.
Serves:
  - Frontend: dashboard/index.html, app.css, app.js
  - Fixtures: tests/fixtures/elpv_samples/*.png
  - REST API:
      POST /api/run      -> Invokes full pipeline and returns telemetry state
      POST /api/approve  -> Electronically signs EnWG §13 dispatch and unlocks SCADA
      GET  /api/incidents-> Returns audit logs from data/logs/incidents.jsonl

Usage:
  python scripts/run_dashboard.py [--port 8000]
"""

from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import os
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

# Ensure project root is on PYTHONPATH
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dashboard_server")

DASHBOARD_DIR = PROJECT_ROOT / "dashboard"
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures" / "elpv_samples"
INCIDENTS_LOG = PROJECT_ROOT / "data" / "logs" / "incidents.jsonl"


class CockpitHandler(BaseHTTPRequestHandler):
    """Handles static web requests and pipeline orchestration REST APIs."""

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            self._serve_file(DASHBOARD_DIR / "index.html", "text/html; charset=utf-8")
        elif path == "/app.css":
            self._serve_file(DASHBOARD_DIR / "app.css", "text/css; charset=utf-8")
        elif path == "/app.js":
            self._serve_file(DASHBOARD_DIR / "app.js", "application/javascript; charset=utf-8")
        elif path.startswith("/fixtures/"):
            filename = os.path.basename(path)
            self._serve_file(FIXTURES_DIR / filename, "image/png")
        elif path == "/api/incidents":
            self._handle_get_incidents()
        elif path == "/api/health":
            self._send_json({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})
        else:
            self.send_error(404, f"Path not found: {path}")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/run":
            self._handle_run_pipeline()
        elif path == "/api/approve":
            self._handle_approve_curtailment()
        else:
            self.send_error(404, f"API endpoint not found: {path}")

    def _serve_file(self, filepath: Path, content_type: str) -> None:
        if not filepath.exists() or not filepath.is_file():
            self.send_error(404, f"File not found: {filepath.name}")
            return

        try:
            content = filepath.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            logger.error("Error serving file %s: %s", filepath, e)
            self.send_error(500, "Internal Server Error")

    def _send_json(self, data: dict | list, status_code: int = 200) -> None:
        body = json.dumps(data, indent=2, default=str).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        raw = self.rfile.read(content_length)
        return json.loads(raw.decode("utf-8"))

    def _handle_run_pipeline(self) -> None:
        try:
            req = self._read_json_body()
            mode = req.get("mode", "fixture")
            topology = req.get("topology", "example-mv")
            image_path = req.get("image_path")
            no_n1 = req.get("no_n1", False)

            resolved_image = None
            if image_path:
                p = PROJECT_ROOT / image_path if not os.path.isabs(image_path) else Path(image_path)
                if p.exists():
                    resolved_image = p

            logger.info("Executing pipeline dispatch: mode=%s, topology=%s, image=%s", mode, topology, resolved_image)

            result = pipeline.run_pipeline(
                smard_mode=mode,
                topology_name=topology,
                asset_image_path=resolved_image,
                run_n1=not no_n1,
                use_lightgbm=True,
                enable_copilot=True,
            )

            self._send_json(result)
        except Exception as e:
            logger.exception("Error executing pipeline:")
            self._send_json({"error": str(e)}, status_code=500)

    def _handle_approve_curtailment(self) -> None:
        try:
            req = self._read_json_body()
            incident_id = req.get("incident_id")
            operator_id = req.get("operator_id", "OP-HUMAN-LEAD")

            if not incident_id:
                self._send_json({"error": "incident_id is required"}, status_code=400)
                return

            if not INCIDENTS_LOG.exists():
                self._send_json({"error": "No incident log found on disk"}, status_code=404)
                return

            lines = INCIDENTS_LOG.read_text(encoding="utf-8").strip().splitlines()
            updated_lines = []
            found = False
            curtailment_mw = 0.0

            now_iso = datetime.now(timezone.utc).isoformat()

            for line in lines:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("incident_id") == incident_id:
                    found = True
                    record["scada_write_blocked"] = False
                    for prop in record.get("proposals", []):
                        prop["operator_approved"] = True
                        prop["approving_operator_id"] = operator_id
                        prop["approval_timestamp"] = now_iso
                        curtailment_mw = prop.get("curtailment_mw", 0.0)
                updated_lines.append(json.dumps(record))

            if not found:
                self._send_json({"error": f"Incident {incident_id} not found"}, status_code=404)
                return

            INCIDENTS_LOG.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
            logger.info("Incident %s electronically signed by %s under EnWG §13.", incident_id, operator_id)

            self._send_json({
                "status": "approved",
                "incident_id": incident_id,
                "operator_id": operator_id,
                "approval_timestamp": now_iso,
                "curtailment_mw": curtailment_mw,
                "scada_write_blocked": False,
            })
        except Exception as e:
            logger.exception("Error approving curtailment:")
            self._send_json({"error": str(e)}, status_code=500)

    def _handle_get_incidents(self) -> None:
        if not INCIDENTS_LOG.exists():
            self._send_json([])
            return

        try:
            lines = INCIDENTS_LOG.read_text(encoding="utf-8").strip().splitlines()
            records = [json.loads(line) for line in lines if line.strip()]
            self._send_json(records)
        except Exception as e:
            logger.error("Error reading incidents log: %s", e)
            self._send_json([])

    def log_message(self, format: str, *args) -> None:
        # Suppress noisy standard request logs, keep clean output
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="ASG-RAOP Operator Cockpit Server")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    args = parser.parse_args()

    server_address = (args.host, args.port)
    httpd = ThreadingHTTPServer(server_address, CockpitHandler)

    print("=" * 70)
    print(" [LIVE] ASG-RAOP Operator Cockpit Live")
    print(f" URL: http://{args.host}:{args.port}")
    print(" Regulatory Standards: BNetzA Redispatch 2.0 | EnWG Sec 13 | EU AI Act Art. 14")
    print("=" * 70)
    print(" Press Ctrl+C to terminate the cockpit server.")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n Shutting down cockpit server...")
        httpd.server_close()


if __name__ == "__main__":
    main()
