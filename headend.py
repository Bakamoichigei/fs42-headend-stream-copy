#!/usr/bin/env python3
"""
headend.py - run every FS42 channel at once as MPEG-TS multicast (stream copy).

Each scheduled station gets its own process that plays the station's FS42
schedule into one continuous transport stream, without decoding or
re-encoding anything. Point one IP decoder (e.g. a VBrick XTV125D) at each
multicast group and feed its composite output to a modulator.

    python3 headend.py                 # all scheduled channels, forever
    python3 headend.py --list          # show channel -> multicast mapping
    python3 headend.py --check         # verify the next 24h of media matches the house format
    python3 headend.py -c 3,4          # only channels 3 and 4
    python3 headend.py --record /tmp/rec --duration 120 --fast   # render to files, faster than realtime

Configuration lives in confs/main_config.json under "headend" - see
docs/headend.md.
"""

import argparse
import datetime
import ipaddress
import json
import logging
import multiprocessing
import os
import signal
import subprocess
import sys
import time

from fs42.station_manager import StationManager
from fs42.station_io import StationIO

logging.basicConfig(format="%(asctime)s %(levelname)s:%(name)s:%(message)s", level=logging.INFO)
log = logging.getLogger("Headend")

DEFAULTS = {
    "multicast_base": "239.42.0.0",   # channel N -> 239.42.0.N
    "port": 5000,
    "ttl": 4,
    "interface": None,                # local IP of the NIC facing the decoders
    "encapsulation": "udp",           # "udp" (raw TS) or "rtp"
    "tos": "0xB8",                    # DSCP EF - harmless on home gear, useful on managed switches
    "slate_file": "runtime/slate.ts",
    "schedule_lead_s": 0.7,
    "auto_extend_schedule": True,
    "provider_name": "FS42",
    "channels": {},                   # per-channel overrides: {"3": {"url": "udp://239.1.1.1:1234"}}
    "exclude": [],                    # channel numbers to leave off the headend
    "path_rewrite": [],               # [{"from": "/media/src/", "to": "/media/ts/", "ext": ".ts"}]
    "live_channels": {},              # {"2": {"name": "PREVUE", "command": "tools/prevue/prevue_channel.sh", "env": {}}}
}


def load_conf():
    raw = StationIO().load_main_config() or {}
    conf = dict(DEFAULTS)
    conf.update(raw.get("headend", {}))
    return conf


def channel_url(station, conf):
    num = int(station["channel_number"])
    override = conf["channels"].get(str(num), {})
    if "url" in override:
        return override["url"]
    group = override.get("group") or str(ipaddress.IPv4Address(conf["multicast_base"]) + num)
    port = override.get("port", conf["port"])
    q = [f"ttl={conf['ttl']}"]
    if conf.get("interface"):
        q.append(f"iface={conf['interface']}")
    if conf.get("tos"):
        q.append(f"tos={conf['tos']}")
    scheme = "rtp" if conf.get("encapsulation") == "rtp" else "udp"
    return f"{scheme}://{group}:{port}?{'&'.join(q)}"


def ffmpeg_url(num, conf):
    """The same multicast destination as channel_url(), in ffmpeg's udp:// syntax."""
    override = conf["channels"].get(str(num), {})
    group = override.get("group") or str(ipaddress.IPv4Address(conf["multicast_base"]) + num)
    port = override.get("port", conf["port"])
    q = f"pkt_size=1316&ttl={conf['ttl']}"
    if conf.get("interface"):
        q += f"&localaddr={conf['interface']}"
    return f"udp://{group}:{port}?{q}"


class LiveChannel:
    """A channel produced by an external live encoder (e.g. the emulated Prevue Guide).

    Quacks like multiprocessing.Process so the supervisor can treat it the same way.
    """

    def __init__(self, num, lconf, url):
        self.num, self.lconf, self.url = num, lconf, url
        self.name = lconf.get("name", f"LIVE{num}")
        self.proc = None

    def start(self):
        env = dict(os.environ)
        env.update({k: str(v) for k, v in self.lconf.get("env", {}).items()})
        env["URL"] = self.url
        env["CHANNEL_NUMBER"] = str(self.num)
        env["CHANNEL_NAME"] = self.name
        self.proc = subprocess.Popen(self.lconf["command"], shell=True, env=env, start_new_session=True)
        return self

    def is_alive(self):
        return self.proc is not None and self.proc.poll() is None

    @property
    def exitcode(self):
        return None if self.proc is None else self.proc.poll()

    def join(self, timeout=None):
        if self.proc is None:
            return
        try:
            self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            pass

    def terminate(self):
        if self.is_alive():
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def select_stations(args, conf):
    sm = StationManager()
    wanted = None
    if args.channels:
        wanted = {int(c) for c in args.channels.split(",")}
    out = []
    for st in sm.stations:
        num = int(st.get("channel_number", 0))
        if wanted is not None and num not in wanted:
            continue
        if num in conf["exclude"]:
            continue
        if str(num) in conf.get("live_channels", {}):
            continue                      # a live encoder owns this channel number
        if not st.get("_has_schedule"):
            log.warning(f"ch {num} '{st['network_name']}' is a {st['network_type']} channel - "
                        "not supported in stream-copy mode, skipping")
            continue
        out.append(st)
    return out


# ---------------------------------------------------------------------------
# --check : does the media on the schedule match the house format?
# ---------------------------------------------------------------------------

SPEC_KEYS_V = ("codec_name", "width", "height", "r_frame_rate", "sample_aspect_ratio", "field_order", "pix_fmt")
SPEC_KEYS_A = ("codec_name", "sample_rate", "channels")


def probe(path):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", path],
                           capture_output=True, text=True, timeout=30)
        j = json.loads(r.stdout or "{}")
    except Exception as e:
        return None, str(e)
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in j.get("streams", []) if s.get("codec_type") == "audio"), None)
    sig = {"format": j.get("format", {}).get("format_name")}
    if v:
        sig.update({f"v.{k}": v.get(k) for k in SPEC_KEYS_V})
    if a:
        sig.update({f"a.{k}": a.get(k) for k in SPEC_KEYS_A})
    return sig, None


def run_check(stations, conf, hours):
    from fs42.headend.schedule_cursor import ScheduleCursor, NoSchedule
    ref, ref_src = None, None
    if conf.get("slate_file") and os.path.exists(conf["slate_file"]):
        ref, _ = probe(conf["slate_file"])
        ref_src = conf["slate_file"]
    else:
        log.warning(f"slate file {conf.get('slate_file')} not found - make one with "
                    "tools/headend_prep.sh --slate (channels will show dead air on gaps)")
    bad = 0
    for st in stations:
        cur = ScheduleCursor(st, conf.get("path_rewrite"))
        t = datetime.datetime.now()
        end = t + datetime.timedelta(hours=hours)
        paths, holes = set(), 0
        while t < end:
            try:
                it = cur.at(t)
            except NoSchedule:
                print(f"  ch {st['channel_number']:>3} {st['network_name']}: schedule ends at {t:%a %H:%M}")
                bad += 1
                break
            if it.path:
                paths.add(it.path)
            else:
                holes += 1
            t = it.ends_at
        problems = []
        for p in sorted(paths):
            if not os.path.exists(p):
                problems.append(f"missing: {p}")
                continue
            sig, err = probe(p)
            if err or not sig:
                problems.append(f"unprobeable: {p} {err or ''}")
                continue
            if ref is None:
                ref, ref_src = sig, p
            diff = {k: (sig.get(k), ref.get(k)) for k in ref if sig.get(k) != ref.get(k)}
            if diff:
                problems.append(f"format mismatch: {p}: " +
                                ", ".join(f"{k}={a} (want {b})" for k, (a, b) in diff.items()))
        status = "OK " if not problems else "BAD"
        print(f"{status} ch {st['channel_number']:>3} {st['network_name']:<24} {len(paths):>4} files, "
              f"{holes} unscheduled gaps")
        for pr in problems[:25]:
            print(f"      {pr}")
        if len(problems) > 25:
            print(f"      ... and {len(problems) - 25} more")
        bad += len(problems)
    if ref:
        print(f"\nreference format (from {ref_src}):")
        for k, v in ref.items():
            print(f"   {k:<24} {v}")
    return 1 if bad else 0


# ---------------------------------------------------------------------------
# supervisor
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="FS42 multichannel stream-copy headend")
    ap.add_argument("-c", "--channels", help="comma-separated channel numbers (default: all scheduled)")
    ap.add_argument("--list", action="store_true", help="print channel -> output mapping and exit")
    ap.add_argument("--check", action="store_true", help="verify upcoming media and exit")
    ap.add_argument("--hours", type=float, default=24, help="how far ahead --check looks (default 24)")
    ap.add_argument("--record", metavar="DIR", help="write each channel to DIR/chNN.ts instead of multicast")
    ap.add_argument("--duration", type=float, help="stop after this many seconds")
    ap.add_argument("--fast", action="store_true", help="with --record: don't pace to realtime")
    ap.add_argument("--start", help="with --fast: pretend it's this time (ISO format)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    conf = load_conf()
    stations = select_stations(args, conf)
    live = {int(n): lc for n, lc in conf.get("live_channels", {}).items()
            if not args.channels or int(n) in {int(c) for c in args.channels.split(",")}}
    if not stations and not live:
        log.error("no schedulable channels found - check confs/ and run station_42.py to build schedules")
        return 1

    urls = {}
    for st in stations:
        num = int(st["channel_number"])
        if args.record:
            os.makedirs(args.record, exist_ok=True)
            urls[num] = f"file://{os.path.abspath(os.path.join(args.record, f'ch{num:02d}.ts'))}"
        else:
            urls[num] = channel_url(st, conf)

    live_urls = {}
    for num in live:
        if args.record:
            os.makedirs(args.record, exist_ok=True)
            live_urls[num] = os.path.abspath(os.path.join(args.record, f"ch{num:02d}.ts"))
        else:
            live_urls[num] = ffmpeg_url(num, conf)

    if args.list:
        print(f"{'ch':>4}  {'network':<24} output")
        rows = [(int(st["channel_number"]), st["network_name"], urls[int(st["channel_number"])]) for st in stations]
        rows += [(n, live[n].get("name", "LIVE") + " (live)", live_urls[n]) for n in live]
        for n, name, u in sorted(rows):
            print(f"{n:>4}  {name:<24} {u}")
        return 0
    if args.check:
        return run_check(stations, conf, args.hours)

    if args.fast and not args.record:
        ap.error("--fast only makes sense with --record")
    start_wall = datetime.datetime.fromisoformat(args.start) if args.start else None
    level = logging.DEBUG if args.verbose else logging.INFO

    ctx = multiprocessing.get_context("fork")
    stop = ctx.Event()
    lock = ctx.Lock()
    from fs42.headend.channel_worker import channel_main

    def spawn(st):
        num = int(st["channel_number"])
        p = ctx.Process(target=channel_main, name=f"ch{num:02d}",
                        args=(st, conf, urls[num], stop, lock, not args.fast, start_wall,
                              args.duration, level), daemon=True)
        p.start()
        return p

    procs = {int(st["channel_number"]): (st, spawn(st)) for st in stations}
    for num, lc in live.items():
        procs[num] = (None, LiveChannel(num, lc, live_urls[num]).start())
    log.info(f"headend up: {len(procs)} channels")
    for num, (st, p) in sorted(procs.items()):
        if st is None:
            log.info(f"  ch {num:>3} {p.name + ' (live)':<24} -> {live_urls[num]}")
        else:
            log.info(f"  ch {num:>3} {st['network_name']:<24} -> {urls[num]}")

    def shutdown(sig, frame):
        log.info("shutting down")
        stop.set()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    restarts = {n: [] for n in procs}
    while not stop.is_set():
        time.sleep(1)
        if all(not p.is_alive() for _, p in procs.values()) and args.duration:
            break
        for num, (st, p) in list(procs.items()):
            if p.is_alive() or args.duration:
                continue
            recent = [t for t in restarts[num] if time.time() - t < 300]
            restarts[num] = recent
            delay = min(60, 2 ** len(recent))
            log.error(f"ch {num} exited (code {p.exitcode}) - restarting in {delay}s")
            time.sleep(delay)
            restarts[num].append(time.time())
            procs[num] = (st, spawn(st)) if st is not None else (None, LiveChannel(num, live[num], live_urls[num]).start())

    stop.set()
    for st, p in procs.values():
        if st is None:
            p.terminate()
    for _, p in procs.values():
        p.join(timeout=5)
        if p.is_alive():
            p.terminate()
    log.info("headend stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
