#!/usr/bin/env python3
"""Drop box -- put a file on this machine from a phone browser.

Stdlib only. Run it, open the URL it prints on your phone, pick a file.
Files land in the folder you ran it from.

It STOPS BY ITSELF once a file arrives. That is deliberate: the phone
terminal this gets driven from has no easy Ctrl-C, and a server you
cannot stop is worse than one that quits too early. Pass --stay to keep
it up for several files, and then `pkill -f drop.py` ends it.

A FILE OF ANY SIZE GOES STRAIGHT TO DISK as it arrives, a megabyte at a
time. The Save my stuff file carries the girls' brains and is several
GB, and the board has 8GB of memory in all: reading it whole first was
how this would have fallen over on exactly the day it mattered.
"""
import html
import os
import re
import shutil
import socket
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8000
STAY = "--stay" in sys.argv[1:]
PAGE = b"""<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>drop box</title>
<style>body{font:16px system-ui;margin:2rem;background:#111;color:#eee}
input,button{font:inherit;padding:.75rem;width:100%;box-sizing:border-box;margin:.5rem 0}
button{background:#2a7;border:0;color:#fff;border-radius:6px}
.ok{color:#2a7}</style>
<h2>drop box</h2>
%ROOM%
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


CHUNK = 1 << 20
# Left free on the board after a file lands. The NVMe also holds her
# memory, his notes and the models, and a disk filled to the last byte
# is how everything else on the board starts failing at once.
ROOM = 256 << 20


def _size(n):
    if n >= 1 << 30:
        return "%.1f GB" % (n / (1 << 30))
    if n >= 1 << 20:
        return "%.1f MB" % (n / (1 << 20))
    return "%d KB" % max(1, round(n / 1024))


def room_left(folder="."):
    """Free space where files land, as a line for the page -- so he sees
    before he sends a 4GB file whether it fits."""
    try:
        return shutil.disk_usage(folder).free
    except OSError:
        return None


def too_big(length, folder="."):
    """A sentence when a file of `length` bytes will not fit, else None.
    Checked BEFORE a byte is written: a disk filled halfway through a
    4GB file is a half file AND a full disk."""
    free = room_left(folder)
    if free is None or length + ROOM <= free:
        return None
    return ("That is %s and the board only has %s free. Nothing was "
            "written." % (_size(length), _size(max(0, free - ROOM))))


def receive(stream, length, content_type, folder=".", chunk=CHUNK):
    """Read ONE uploaded file off a multipart POST and write it into
    `folder` as it arrives. Returns (name it was saved as, bytes), or
    (None, 0) when there was no file in it or it was cut short.

    Never holds more than a chunk in memory. It lands as `<name>.part`
    and is renamed only once it is whole, so an upload the WiFi cut off
    never leaves a file that looks finished."""
    match = re.search(r'boundary=("?)([^";,]+)\1', content_type or "")
    if not match or length <= 0:
        return None, 0
    delim = b"\r\n--" + match.group(2).encode()
    # The body opens with "--boundary"; every LATER part is preceded by
    # CRLF as well. Pretending the body started with a CRLF makes every
    # part the same shape, so one search finds them all.
    state = {"buf": b"\r\n", "left": length}

    def fill():
        if state["left"] <= 0:
            return False
        piece = stream.read(min(chunk, state["left"]))
        if not piece:
            state["left"] = 0
            return False
        state["left"] -= len(piece)
        state["buf"] += piece
        return True

    def until(mark, sink, cap=None):
        """Hand everything before `mark` to sink; True once it is found.
        Holds back the last len(mark)-1 bytes, which could be the start
        of the mark split across two reads."""
        seen = 0
        while True:
            buf = state["buf"]
            at = buf.find(mark)
            if at >= 0:
                sink(buf[:at])
                state["buf"] = buf[at + len(mark):]
                return True
            keep = len(mark) - 1
            if len(buf) > keep:
                sink(buf[:len(buf) - keep])
                seen += len(buf) - keep
                state["buf"] = buf[len(buf) - keep:]
            if cap is not None and seen > cap:
                return False
            if not fill():
                return False

    def drop(_):
        pass

    if not until(delim, drop):
        return None, 0
    while True:
        while len(state["buf"]) < 2 and fill():
            pass
        if state["buf"][:2] != b"\r\n":
            return None, 0                   # "--": the last part, no file
        head = []
        if not until(b"\r\n\r\n", head.append, cap=64 << 10):
            return None, 0
        found = re.search(rb'filename="([^"]*)"', b"".join(head))
        if not (found and found.group(1)):
            if not until(delim, drop):
                return None, 0
            continue
        # Keep the basename only -- a crafted filename must never be
        # able to write outside the folder this was started in.
        raw = found.group(1).decode(errors="replace")
        safe = os.path.basename(raw.replace("\\", "/")) or "dropped.bin"
        if safe in (".", ".."):
            safe = "dropped.bin"
        final = os.path.join(folder, safe)
        part = final + ".part"
        wrote = [0]
        with open(part, "wb") as out:
            def keep(data):
                out.write(data)
                wrote[0] += len(data)
            whole = until(delim, keep)
        if not whole:
            os.remove(part)
            return None, 0
        os.replace(part, final)
        return safe, wrote[0]


class Drop(BaseHTTPRequestHandler):
    def _page(self, msg=b""):
        free = room_left()
        room = (b"" if free is None else
                ("<p>Room on the board: %s</p>" % _size(free)).encode())
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGE.replace(b"%ROOM%", room)
                         .replace(b"%MSG%", msg))

    def do_GET(self):
        self._page()

    def do_POST(self):
        size = int(self.headers.get("Content-Length", 0) or 0)
        full = too_big(size)
        if full:
            print("  REFUSED: " + full)
            self.close_connection = True
            self._page(("<p>%s</p>" % html.escape(full)).encode())
            return
        print(f"  receiving {_size(size)}...")
        safe, got = receive(self.rfile, size,
                            self.headers.get("Content-Type", ""))
        if not safe:
            self._page(b"<p>No whole file in that. Try again.</p>")
            return
        print(f"  got {safe}  ({got:,} bytes)")
        note = "" if STAY else "<p>Drop box closed. You're done here.</p>"
        self._page(f"<p class=ok>Saved <b>{html.escape(safe)}</b> "
                   f"({got:,} bytes)</p>{note}".encode())
        if not STAY:
            # Answer the phone FIRST, then stop -- shutting down from
            # inside a handler would cut the reply off mid-flight, and
            # the phone would show a network error over a file that
            # actually arrived intact.
            self.server.done = True

    def log_message(self, *a):
        pass                              # the print above is the only log


if __name__ == "__main__":
    where = os.getcwd()
    print(f"\n  Drop box. Files land in: {where}")
    print(f"  Open this on your phone:  http://{lan_ip()}:{PORT}")
    print("  Stops on its own once a file lands."
          if not STAY else "  Staying up. Stop it with:  pkill -f drop.py")
    print()
    server = HTTPServer(("0.0.0.0", PORT), Drop)
    server.done = False
    try:
        while not server.done:
            server.handle_request()
    except KeyboardInterrupt:
        print("\n  Stopped.\n")
        sys.exit(0)
    print("  Done.\n")
