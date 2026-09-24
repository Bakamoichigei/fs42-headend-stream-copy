#!/usr/bin/env python3
"""
make_channels_xml.py - write one channels.xml per VBrick XTV125D decoder.

Each decoder sits on one headend channel in "Local Fullscreen Mode": at power-on
it plays its one stream full-screen, with no channel guide. This reads the
headend block of confs/main_config.json (multicast_base, port, per-channel
overrides) so the groups always match what headend.py sends.

    python3 tools/xtv125d/make_channels_xml.py                 # channels 2-13 -> runtime/xtv125d/chNN/channels.xml
    python3 tools/xtv125d/make_channels_xml.py -c 7,42         # just these
    python3 tools/xtv125d/make_channels_xml.py --print -c 7    # show one on stdout

Standard library only; it doesn't need FS42 installed. See docs/xtv125d.md.
"""

import argparse
import ipaddress
import json
import os
import sys
import urllib.parse
from xml.sax.saxutils import escape

DEFAULTS = {"multicast_base": "239.42.0.0", "port": 5000, "encapsulation": "udp",
            "channels": {}, "live_channels": {}}


def load_headend_conf(path):
    conf = dict(DEFAULTS)
    try:
        with open(path) as f:
            conf.update((json.loads(f.read() or "{}") or {}).get("headend", {}))
    except FileNotFoundError:
        print(f"note: {path} not found, using the headend defaults", file=sys.stderr)
    except json.JSONDecodeError as e:
        sys.exit(f"error: {path} isn't valid JSON ({e})")
    return conf


def stream_url(num, conf):
    """tv://group:port - the XTV125D's syntax for an MPEG-2 TS multicast."""
    o = conf.get("channels", {}).get(str(num), {})
    if "url" in o:
        u = urllib.parse.urlsplit(o["url"])
        group, port = u.hostname, u.port or conf["port"]
    else:
        group = o.get("group") or str(ipaddress.IPv4Address(conf["multicast_base"]) + num)
        port = o.get("port", conf["port"])
    return f"tv://{group}:{port}"


def channel_name(num, conf):
    lc = conf.get("live_channels", {}).get(str(num))
    return f"BAKACAST {num} {lc['name']}" if lc and lc.get("name") else f"BAKACAST {num}"


def channels_xml(num, conf, title="Bakacast"):
    # Laid out exactly like the manual's sample (no comments), in case the box's parser is fussy.
    url = escape(stream_url(num, conf))
    name = escape(channel_name(num, conf))
    return f"""<?xml version="1.0" encoding="utf-8"?>
<STBLocalUI>
  <Title>{escape(title)}</Title>
  <GlobalMsg></GlobalMsg>
  <FullScreen>1</FullScreen>
  <Stream>
    <ProgramName>{name}</ProgramName>
    <Message>{url}</Message>
    <URL>{url}</URL>
  </Stream>
</STBLocalUI>
"""


def parse_channels(spec):
    out = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += range(int(a), int(b) + 1)
        elif part:
            out.append(int(part))
    return out


def main():
    ap = argparse.ArgumentParser(description="Write XTV125D channels.xml files for the headend's channels")
    ap.add_argument("-c", "--channels", default="2-13", help="e.g. 2-13 or 3,7,42 (default 2-13)")
    ap.add_argument("--config", default="confs/main_config.json")
    ap.add_argument("--out", default="runtime/xtv125d", help="output folder (default runtime/xtv125d)")
    ap.add_argument("--title", default="Bakacast")
    ap.add_argument("--print", action="store_true", help="print to stdout instead of writing files")
    args = ap.parse_args()

    conf = load_headend_conf(args.config)
    if conf.get("encapsulation") == "rtp":
        print("warning: the headend is set to RTP; the XTV125D's tv:// examples are raw UDP. "
              "Use \"encapsulation\": \"udp\" unless RTP has been tested on the box.", file=sys.stderr)

    for num in parse_channels(args.channels):
        xml = channels_xml(num, conf, args.title)
        if args.print:
            print(xml)
            continue
        d = os.path.join(args.out, f"ch{num:02d}")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "channels.xml"), "w", newline="\n") as f:
            f.write(xml)
        print(f"ch {num:>3}  {stream_url(num, conf):<24} -> {d}/channels.xml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
