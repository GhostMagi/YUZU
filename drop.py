#!/usr/bin/env python3
"""Drop box -- put a file on this machine from a phone browser.

Stdlib only. Run it, open the URL it prints on your phone, pick a file.
Files land in the folder you ran it from. Ctrl-C to stop.
"""
import html
import os
import re
import socket
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8000
PAGE = b"""<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>drop box</title>
<style>body{font:16px system-ui;margin:2rem;background:#111;color:#eee}
input,button{font:inherit;padding:.75rem;width:100%;box-sizing:border-box;margin:.5rem 0}
button{background:#2a7;border:0;color:#fff;border-radius:6px}
.ok{color:#2a7}</style>
<h2>drop box</h2>
<form method=post enctype=multipart/form-data>
<input type=file name=f required>
<button>send to the board</button>
</form>
%MSG%
"""


def lan_ip():
    """The address a phone on the same WiFi can actually reach."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))       # no packet is sent; picks the route
        return s.getsockname()[0]
    finally:
        s.close()


def one_file(body, content_type):
    """Pull (filename, bytes) out of a multipart POST. One field, no deps."""
    match = re.search(rb'boundary=("?)([^";,]+)\1', content_type.encode())
    if not match:
        return None, None
    sep = b"--" + match.group(2)
    for part in body.split(sep):
        head, _, data = part.partition(b"\r\n\r\n")
        name = re.search(rb'filename="([^"]*)"', head)
        if name and name.group(1) and data:
            return name.group(1).decode(errors="replace"), data[:-2]
    return None, None


class Drop(BaseHTTPRequestHandler):
    def _page(self, msg=b""):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGE.replace(b"%MSG%", msg))

    def do_GET(self):
        self._page()

    def do_POST(self):
        size = int(self.headers.get("Content-Length", 0))
        name, data = one_file(self.rfile.read(size),
                              self.headers.get("Content-Type", ""))
        if not name:
            self._page(b"<p>No file in that. Try again.</p>")
            return
        # Keep the basename only -- a crafted filename must never be able to
        # write outside the folder this was started in.
        safe = os.path.basename(name.replace("\\", "/")) or "dropped.bin"
        with open(safe, "wb") as out:
            out.write(data)
        print(f"  got {safe}  ({len(data):,} bytes)")
        self._page(f"<p class=ok>Saved <b>{html.escape(safe)}</b> "
                   f"({len(data):,} bytes)</p>".encode())

    def log_message(self, *a):
        pass                              # the print above is the only log


if __name__ == "__main__":
    where = os.getcwd()
    print(f"\n  Drop box. Files land in: {where}")
    print(f"  Open this on your phone:  http://{lan_ip()}:{PORT}")
    print("  Ctrl-C when you're done.\n")
    try:
        HTTPServer(("0.0.0.0", PORT), Drop).serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.\n")
        sys.exit(0)
