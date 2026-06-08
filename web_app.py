# web_app.py
# Lightweight local web app for the KOL recommendation tool.

from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from api import get_filter_options, recommend
from utils import PROJECT_ROOT


STATIC_DIR = PROJECT_ROOT / "static"


class KOLRequestHandler(BaseHTTPRequestHandler):
    server_version = "KOLMatcher/1.0"

    def do_GET(self) -> None:
        if self.path == "/api/options":
            self._send_json(get_filter_options())
            return

        path = self.path.split("?", 1)[0]
        if path in ("", "/"):
            path = "/index.html"
        self._serve_static(path)

    def do_POST(self) -> None:
        if self.path != "/api/recommend":
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            self._send_json(recommend(payload))
        except Exception as exc:  # Keep the UI resilient during local demos.
            self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[web] {self.address_string()} - {fmt % args}")

    def _serve_static(self, raw_path: str) -> None:
        relative = unquote(raw_path).lstrip("/")
        file_path = (STATIC_DIR / relative).resolve()

        if STATIC_DIR.resolve() not in file_path.parents and file_path != STATIC_DIR.resolve():
            self._send_json({"error": "Forbidden"}, HTTPStatus.FORBIDDEN)
            return

        if not file_path.is_file():
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return

        content_type, _ = mimetypes.guess_type(file_path)
        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), KOLRequestHandler)
    print(f"AI KOL 达人匹配助手已启动：http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start the AI KOL matcher web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    run(args.host, args.port)
