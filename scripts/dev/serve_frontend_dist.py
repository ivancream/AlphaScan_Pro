from __future__ import annotations

import http.server
import socketserver
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "frontend" / "dist"
PORT = 1420


class SpaHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST), **kwargs)

    def send_head(self):
        requested = DIST / self.path.lstrip("/").split("?", 1)[0]
        if self.path != "/" and not requested.exists():
            self.path = "/index.html"
        return super().send_head()


if __name__ == "__main__":
    if not DIST.exists():
        raise SystemExit(f"Missing frontend dist folder: {DIST}")
    with socketserver.TCPServer(("127.0.0.1", PORT), SpaHandler) as httpd:
        print(f"Serving AlphaScan frontend at http://localhost:{PORT}/")
        httpd.serve_forever()
