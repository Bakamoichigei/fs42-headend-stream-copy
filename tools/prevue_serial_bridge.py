#!/usr/bin/env python3
"""
prevue_serial_bridge.py - a virtual serial cable between prevue_feed.py and FS-UAE.

Creates a pseudo-terminal (the emulated Amiga's serial port plugs into its
slave side via FS-UAE's `serial_port` option) and listens on TCP; whatever a
client (prevue_feed.py) sends is written to the Amiga. The pty stays put
across feeder restarts, so the emulator never loses its "cable".

    tools/prevue_serial_bridge.py --link /tmp/prevue-serial --port 5541

Start it before FS-UAE; stop it after.
"""

import argparse
import os
import select
import signal
import socket
import termios
import tty


def _on_term(signum, frame):
    raise KeyboardInterrupt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--link", default="/tmp/prevue-serial", help="symlink to create for the pty slave")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5541)
    args = ap.parse_args()

    signal.signal(signal.SIGTERM, _on_term)
    master, slave = os.openpty()
    tty.setraw(slave)
    attrs = termios.tcgetattr(slave)
    attrs[4] = attrs[5] = termios.B2400                   # ispeed / ospeed
    termios.tcsetattr(slave, termios.TCSANOW, attrs)
    slave_name = os.ttyname(slave)
    try:
        os.unlink(args.link)
    except FileNotFoundError:
        pass
    os.symlink(slave_name, args.link)
    print(f"serial port: {args.link} -> {slave_name}", flush=True)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.host, args.port))
    srv.listen(1)
    print(f"listening on {args.host}:{args.port}", flush=True)

    try:
        while True:
            conn, addr = srv.accept()
            print(f"feeder connected from {addr[0]}", flush=True)
            with conn:
                while True:
                    r, _, _ = select.select([conn, master], [], [])
                    if master in r:                       # anything the Amiga sends back: discard
                        try:
                            os.read(master, 4096)
                        except OSError:
                            pass
                    if conn in r:
                        data = conn.recv(4096)
                        if not data:
                            break
                        os.write(master, data)
            print("feeder disconnected", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            os.unlink(args.link)
        except OSError:
            pass


if __name__ == "__main__":
    main()
