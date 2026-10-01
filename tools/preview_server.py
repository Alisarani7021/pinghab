#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
preview_server.py — پیش‌نمایش زندهٔ «پینگ‌هاب» در فضای کاری.

فایل web/dns-radar.html (سایت ۱۹ پنلی با طرح v3) را سرو می‌کند و درخواست‌های /api/*
را به ورکرِ زندهٔ کلادفلر پراکسی می‌کند؛ پس همهٔ دکمه‌ها و سنجش‌ها داخل پیش‌نمایش هم کار می‌کنند.

اجرا:  python3 tools/preview_server.py [port]
"""
import http.server
import socketserver
import sys
import urllib.request
import urllib.error
from pathlib import Path

SITE = "https://pinghab.catclient-59gk2mui.workers.dev"
ROOT = Path(__file__).resolve().parents[1] / "web"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
SKIP = {"content-encoding", "transfer-encoding", "connection", "content-length"}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, fmt, *args):
        print("[preview]", self.address_string(), fmt % args, flush=True)

    def _proxy(self):
        url = SITE + self.path
        data = None
        if self.command == "POST":
            n = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(n) if n else b""
        req = urllib.request.Request(url, data=data, method=self.command,
                                     headers={"User-Agent": "Mozilla/5.0 (Pinghab preview)",
                                              "Content-Type": self.headers.get("Content-Type", "application/json"),
                                              "Accept": self.headers.get("Accept", "*/*")})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                body = r.read()
                self.send_response(r.status)
                for k, v in r.headers.items():
                    if k.lower() not in SKIP:
                        self.send_header(k, v)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        except urllib.error.HTTPError as e:
            body = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            msg = ('{"ok":false,"error":"proxy: %s"}' % str(e)[:80]).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._proxy()
        if self.path in ("/", "/app", "/index.html", "/dns-radar.html"):
            self.path = "/dns-radar.html"
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            return self._proxy()
        self.send_response(404)
        self.end_headers()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("0.0.0.0", PORT), Handler) as httpd:
        print(f"Pinghab preview on http://0.0.0.0:{PORT}  (API → {SITE})", flush=True)
        httpd.serve_forever()
