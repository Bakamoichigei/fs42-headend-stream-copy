#!/usr/bin/env python3
"""
prevue_feed.py - feed FS42's schedules to an emulated Prevue Guide Amiga.

The real Prevue boxes received their listings over a 2400-baud serial line
from the satellite data feed. This plays that role: it builds the channel
lineup and program listings from FS42's schedules and sends them, in the
UVSG protocol, to the emulated Amiga's serial port (exposed as a TCP
socket - see docs/prevue.md).

    python3 prevue_feed.py                     # run forever (refreshes listings + clock)
    python3 prevue_feed.py --once              # send everything once and exit
    python3 prevue_feed.py --dump feed.bin     # write the byte stream to a file instead
    python3 prevue_feed.py --print             # show the lineup/listings it would send

Configuration: "prevue" block in confs/main_config.json (see docs/prevue.md).
"""

import argparse
import datetime
import logging
import socket
import sys
import time

from fs42.prevue import protocol as P
# FS42 itself is imported lazily, so --demo works on a machine without an FS42 install

logging.basicConfig(format="%(asctime)s %(levelname)s:%(name)s:%(message)s", level=logging.INFO)
log = logging.getLogger("PrevueFeed")

DEFAULTS = {
    "host": "127.0.0.1",
    "port": 5541,
    "software": "9",                  # "9" (9.0.4) or "7.8.3"
    "display_format": "grid",         # "grid" or "scroll" (the list format)
    "timezone": 6,                    # hours west of GMT the box applies; see docs/prevue.md
    "observes_dst": True,
    "scroll_speed": 3,                # 1 (slow) .. 8
    "timeslots_forward": 4,
    "title": "BAKACAST CABLE",
    "ads": [
        [["BEFORE YOU VIEW,", "center"], ["PREVUE!", "center"]],
    ],
    "channels": {},                   # {"3": {"call_letters": "WFSA", "hilite": true, "movies": false}}
    "exclude": [],
    "movie_minutes": 90,              # blocks at least this long get the movie colour
    "refresh_minutes": 30,
    "baud": 2400,
}


def load_conf(demo=False):
    if demo:
        return dict(DEFAULTS)
    from fs42.station_io import StationIO
    raw = StationIO().load_main_config() or {}
    conf = dict(DEFAULTS)
    conf.update(raw.get("prevue", {}))
    return conf


class Link:
    """Byte sink with real serial-line pacing."""

    def __init__(self, host=None, port=None, dump=None, baud=2400, pace=True):
        self.host, self.port, self.baud, self.pace = host, port, baud, pace
        self.sock = None
        self.dump = open(dump, "wb") if dump else None

    def connect(self):
        if self.dump:
            return
        while True:
            try:
                self.sock = socket.create_connection((self.host, self.port), timeout=10)
                self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                log.info(f"connected to Prevue serial port at {self.host}:{self.port}")
                return
            except OSError as e:
                log.warning(f"can't reach {self.host}:{self.port} ({e}) - is the emulator running? retrying in 10s")
                time.sleep(10)

    def send(self, data):
        if self.dump:
            self.dump.write(data)
            return
        try:
            self.sock.sendall(data)
        except OSError as e:
            log.warning(f"send failed ({e}) - reconnecting")
            self.connect()
            self.sock.sendall(data)
        if self.pace:
            time.sleep(P.send_duration(data, self.baud))

    def close(self):
        if self.sock:
            self.sock.close()
        if self.dump:
            self.dump.close()


def dst_period(now):
    """Next (start, end) local DST boundaries as naive datetimes, or None."""
    local = datetime.datetime.now().astimezone().tzinfo
    t = now.replace(minute=0, second=0, microsecond=0)
    def isdst(x):
        return bool(x.replace(tzinfo=local).astimezone().dst())
    try:
        start = end = None
        cur = isdst(t)
        for h in range(24 * 400):
            x = t + datetime.timedelta(hours=h)
            d = isdst(x)
            if d != cur:
                if d and start is None:
                    start = x
                elif not d and start is not None:
                    end = x
                    break
                cur = d
        return (start, end) if start and end else None
    except Exception:
        return None


def config_commands(conf):
    sw9 = str(conf["software"]).startswith("9")
    out = [
        P.configuration(timeslots_forward=int(conf["timeslots_forward"]), scroll_speed=int(conf["scroll_speed"]),
                        timezone=int(conf["timezone"]), observes_dst=bool(conf["observes_dst"])),
        P.new_look_configuration(conf["display_format"], "S", 2 if sw9 else None),
    ]
    return out


def clock_commands(conf, now):
    local_dst = bool(datetime.datetime.now().astimezone().dst())
    out = [P.clock(now, dst=local_dst)]
    period = dst_period(now) if conf["observes_dst"] else None
    if period:
        out.append(P.dst(period[0], period[1], "local"))
        out.append(P.dst(period[0], period[1], "global"))
    return out


def ad_commands(conf):
    out = [P.local_ads_reset()]
    for i, ad in enumerate(conf.get("ads", []), start=1):
        lines = [tuple(x) if isinstance(x, list) else x for x in ad]
        out.append(P.local_ad(i, lines))
    return out


DEMO_LINEUP = [
    # (channel, call letters, flags, [(minutes long, title, is_movie), ...] repeating from 5 AM)
    ("2", "PREVUE", 0, [(30, "Prevue Guide", False)]),
    ("3", "WFSA", 0, [(30, "Action News", False), (30, "Wheel of Fortune", False), (60, "Murder, She Wrote", False)]),
    ("4", "KMOV", 0, [(120, "Back to the Future", True), (120, "The Goonies", True)]),
    ("5", "LOOP5", 0, [(30, "Cartoon Express", False)]),
    ("6", "WPVI", 0x02, [(60, "Local Programming", False)]),
]


def demo_listings(now):
    """A made-up lineup, for testing against the real software without FS42."""
    day0 = P.listings_day_start(now)
    chans, progs = [], {}
    for num, call, flags, shows in DEMO_LINEUP:
        chans.append({"source_id": call[:6], "number": num, "call_letters": call, "flags": P.CH_NONE | flags})
        for d in range(2):
            start = day0 + datetime.timedelta(days=d)
            jd = P.julian_day(start)
            t, i = start, 0
            while t < start + datetime.timedelta(days=1):
                mins, title_, movie = shows[i % len(shows)]
                progs.setdefault(jd, []).append((P.timeslot(t), call[:6], title_, P.PG_MOVIE if movie else P.PG_NONE))
                t += datetime.timedelta(minutes=mins)
                i += 1
    return P.julian_day(now), chans, progs


def listings_commands(conf, now):
    if conf.get("_demo"):
        jd, chans, progs = demo_listings(now)
        out = [P.channels(jd, chans)]
        n = 0
        for day in sorted(progs, key=lambda d: (d - jd) % 256):
            for slot, sid, title_, flags in progs[day]:
                out.append(P.program(day, slot, sid, title_, flags))
                n += 1
        return out, chans, progs, n
    from fs42.prevue import listings as L
    from fs42.station_manager import StationManager
    stations = StationManager().stations
    jd, chans, progs = L.build(stations, conf.get("channels", {}), now,
                               exclude=set(int(x) for x in conf.get("exclude", [])),
                               movie_minutes=conf.get("movie_minutes", 90))
    out = [P.channels(jd, chans)]
    n = 0
    for day in sorted(progs, key=lambda d: (d - jd) % 256):
        for slot, sid, title_, flags in progs[day]:
            out.append(P.program(day, slot, sid, title_, flags))
            n += 1
    return out, chans, progs, n


def full_update(link, conf, now, first=False):
    cmds, chans, progs, n = listings_commands(conf, now)
    batch = [P.box_on("*")]
    batch += config_commands(conf)
    batch += clock_commands(conf, now)
    if first:
        batch += [P.title(conf["title"], "center")]
        batch += ad_commands(conf)
    batch += cmds
    batch += [P.box_off()]
    total = sum(len(b) for b in batch)
    log.info(f"sending {len(chans)} channels, {n} programs ({total} bytes, "
             f"~{P.send_duration(b''.join(batch), conf['baud']):.0f}s at {conf['baud']} baud)")
    for b in batch:
        link.send(b)


def print_listings(conf):
    now = datetime.datetime.now()
    _, chans, progs, n = listings_commands(conf, now)
    print(f"{'src':<7}{'ch':>4}  call     flags")
    for c in chans:
        print(f"{c['source_id']:<7}{c['number']:>4}  {c['call_letters']:<8} 0x{c['flags']:02x}")
    for day in sorted(progs):
        print(f"\nlistings day {day}:")
        for slot, sid, t, f in sorted(progs[day]):
            hh = (5 * 60 + (slot - 1) * 30) // 60 % 24
            mm = (slot - 1) * 30 % 60
            print(f"  {hh:02d}:{mm:02d} [{slot:>2}] {sid:<7} {'M ' if f & P.PG_MOVIE else '  '}{t}")


def main():
    ap = argparse.ArgumentParser(description="Feed FS42 listings to an emulated Prevue Guide")
    ap.add_argument("--host")
    ap.add_argument("--port", type=int)
    ap.add_argument("--once", action="store_true", help="send once and exit")
    ap.add_argument("--dump", metavar="FILE", help="write the byte stream to FILE instead of the emulator")
    ap.add_argument("--print", action="store_true", help="print the lineup and listings, send nothing")
    ap.add_argument("--demo", action="store_true", help="send a built-in test lineup instead of FS42's schedules")
    ap.add_argument("--format", choices=["grid", "scroll"], help="override display_format")
    ap.add_argument("--software", choices=["9", "7.8.3"], help="override software version")
    args = ap.parse_args()

    conf = load_conf(args.demo)
    conf["_demo"] = args.demo
    if args.format:
        conf["display_format"] = args.format
    if args.software:
        conf["software"] = args.software
    if args.host:
        conf["host"] = args.host
    if args.port:
        conf["port"] = args.port
    if args.print:
        print_listings(conf)
        return 0

    link = Link(conf["host"], conf["port"], args.dump, conf["baud"], pace=not args.dump)
    link.connect()
    first = True
    last_day = None
    try:
        while True:
            now = datetime.datetime.now()
            full_update(link, conf, now, first=first or P.julian_day(now) != last_day)
            first = False
            last_day = P.julian_day(now)
            if args.once or args.dump:
                break
            # wake just after the next half hour (or refresh interval)
            step = int(conf["refresh_minutes"])
            nxt = now.replace(second=5, microsecond=0) + datetime.timedelta(minutes=step - now.minute % step)
            time.sleep(max(30, (nxt - datetime.datetime.now()).total_seconds()))
    except KeyboardInterrupt:
        pass
    finally:
        link.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
