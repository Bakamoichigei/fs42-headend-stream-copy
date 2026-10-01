#!/usr/bin/env python3
"""Convert an ESQ (Prevue Guide) saved schedule, curday.dat, into prevue_feed.py listings JSON.

curday.dat is ESQ's own on-disk copy of the listings it last received, usually
PowerPacker-compressed (PP20). This decompresses it, parses the channel and
program records, and writes the `--listings` JSON format that prevue_feed.py
already sends, so the serial side reuses the tested protocol and pacing code.

Usage (no venv needed, stdlib only):
    py tools/prevue/curday2listings.py curday.dat -o confs/examples/prevue_la1999.json
    py prevue_feed.py --listings confs/examples/prevue_la1999.json --print
    py prevue_feed.py --listings confs/examples/prevue_la1999.json --port 1234 --once
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

SLOT_MIN = 30
DAY_START_MIN = 5 * 60  # Prevue slot 1 = 05:00 in the box's data time zone


# --------------------------------------------------------------------------- PP20

def pp20_decrunch(d: bytes) -> bytes:
    """Decompress a PowerPacker PP20 data file."""
    if d[:4] != b"PP20":
        raise ValueError("not a PP20 file")
    offlens = d[4:8]
    dest_len = int.from_bytes(d[-4:-1], "big")
    src = d[8:-4]
    pos, buf, left = len(src), 0, 0

    def bits(n: int) -> int:
        nonlocal pos, buf, left
        while left < n:
            pos -= 1
            if pos < 0:
                raise ValueError("PP20 stream truncated")
            buf |= src[pos] << left
            left += 8
        v = 0
        for _ in range(n):
            v = (v << 1) | (buf & 1)
            buf >>= 1
        left -= n
        return v

    out = bytearray(dest_len)
    o = dest_len
    bits(d[-1])
    while o > 0:
        if bits(1) == 0:
            todo = 1
            while True:
                x = bits(2)
                todo += x
                if x != 3:
                    break
            for _ in range(todo):
                o -= 1
                out[o] = bits(8)
            if o == 0:
                break
        x = bits(2)
        offbits, todo = offlens[x], x + 2
        if x == 3:
            if bits(1) == 0:
                offbits = 7
            off = bits(offbits)
            while True:
                y = bits(3)
                todo += y
                if y != 7:
                    break
        else:
            off = bits(offbits)
        for _ in range(todo):
            o -= 1
            out[o] = out[o + 1 + off]
    return bytes(out)


# --------------------------------------------------------------------------- parse

@dataclass
class Program:
    slot: int          # 1..48
    attr: int          # bit 0x02 = movie, 0x10 = sports (0x01/0x08 meaning unknown)
    category: int      # 34 series, 22 news, 19 kids, 5 sports, 1 movie, 0 text
    title: bytes


@dataclass
class Channel:
    number: str        # "" for text-only / local-origination sources
    source: str
    call: str
    flags: int         # header byte 27: 0x80 broadcast/basic, 0x40 premium, 0x20 text
    programs: list[Program] = field(default_factory=list)


_MARK = re.compile(rb"\x03([A-Z0-9$]{2,6})\x00")


def _cstr(b: bytes) -> str:
    return b.split(b"\x00", 1)[0].decode("latin-1").strip()


def parse_curday(d: bytes) -> list[Channel]:
    marks = list(_MARK.finditer(d))
    chans: list[Channel] = []
    for i, m in enumerate(marks):
        h = d.rfind(b"[", 0, m.start())
        hdr = d[h:m.start()]
        if h < 0 or len(hdr) < 28 or _cstr(hdr[12:19]) != m.group(1).decode():
            continue  # not a channel header (marker matched inside a title)
        ch = Channel(number=hdr[1:6].decode("latin-1").strip(),
                     source=m.group(1).decode(),
                     call=_cstr(hdr[19:27]),
                     flags=hdr[27])
        end = d.rfind(b"[", 0, marks[i + 1].start()) if i + 1 < len(marks) else len(d)
        f = d[m.end():end].split(b"\x00")
        j = 0
        while j + 5 < len(f) and f[j].isdigit() and int(f[j]) <= 48:
            ch.programs.append(Program(int(f[j]), int(f[j + 1] or 0),
                                       int(f[j + 2] or 0), f[j + 5]))
            j += 6
        chans.append(ch)
    return chans


# --------------------------------------------------------------------------- convert

_GLYPHS = re.compile(rb"\s*[\x80-\xbf]")     # Prevue font icons: ratings, CC, premiere, etc.
_MOVIE = re.compile(rb'^((?:\(\s*\d+:\d\d\)\s*)?"[^"]+")[^(]*?(\(\d{4}\))?')


def clean_title(raw: bytes, keep_glyphs: bool, short_movie: bool, movie: bool) -> str:
    t = raw
    if movie and short_movie:
        m = _MOVIE.match(t)
        if m:
            t = m.group(1) + (b" " + m.group(2) if m.group(2) else b"")
    if not keep_glyphs:
        t = _GLYPHS.sub(b"", t)
        t = re.sub(rb"\s*\|\s*", b" ", t)   # '|' = stereo marker in the Prevue font
    return re.sub(r"\s+", " ", t.decode("latin-1")).strip()


def slot_time(slot: int, shift_min: int) -> str:
    m = (DAY_START_MIN + (slot - 1) * SLOT_MIN + shift_min) % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


def to_listings(chans: list[Channel], shift_min: int, keep_glyphs: bool,
                short_movie: bool, premium_hilite: bool,
                only: set[int] | None) -> tuple[dict, list[str]]:
    out: list[dict] = []
    notes: list[str] = []
    skipped_text: list[str] = []
    for ch in chans:
        if not ch.number.isdigit():
            if ch.programs:
                skipped_text.append(ch.source)
            continue
        num = int(ch.number)
        if only is not None and num not in only:
            continue
        if not ch.programs:
            notes.append(f"ch {num} {ch.call or ch.source}: no listings, skipped")
            continue
        sched: dict[str, object] = {}
        for k, p in enumerate(ch.programs):
            movie = bool(p.attr & 0x02)
            sports = bool(p.attr & 0x10)
            title = clean_title(p.title, keep_glyphs, short_movie, movie) or "To Be Announced"
            # Slots before 05:00 after the shift would wrap to the end of the listings day;
            # pin an opening program there to 05:00 so the morning isn't blank.
            when = slot_time(p.slot, shift_min)
            if k == 0 and DAY_START_MIN + (p.slot - 1) * SLOT_MIN + shift_min < DAY_START_MIN:
                when = "05:00"
            entry: object = {"title": title, "movie": True} if movie else \
                            {"title": title, "sports": True} if sports else title
            sched[when] = entry
        c: dict[str, object] = {"number": num, "call": (ch.call or ch.source)[:7],
                                "source": ch.source[:6], "schedule": sched}
        if premium_hilite and ch.flags & 0x40:
            c["hilite"] = True
        out.append(c)
    if skipped_text:
        notes.append(f"skipped {len(skipped_text)} text/ad sources with no channel number: "
                     + ", ".join(skipped_text))
    nums = [c["number"] for c in out]
    for n in sorted({n for n in nums if nums.count(n) > 1}):
        notes.append(f"ch {n} is shared by {nums.count(n)} sources (part-time channel)")
    return {"channels": out}, notes


def parse_range(s: str) -> set[int]:
    r: set[int] = set()
    for part in s.split(","):
        a, _, b = part.partition("-")
        r.update(range(int(a), int(b or a) + 1))
    return r


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("curday", type=Path, help="curday.dat (PP20-packed or already unpacked)")
    ap.add_argument("-o", "--out", type=Path, help="write JSON here (default: stdout)")
    ap.add_argument("--shift-hours", type=float, default=-2.0,
                    help="hours added to the box's data time (default -2: this disk's LA box "
                         "ran timezone 8 against Central-based slots, so shows land at the "
                         "times they aired in LA). 0 = raw slot times.")
    ap.add_argument("--start", metavar="HH:MM|now",
                    help="instead of --shift-hours, slide the schedule so its first listed "
                         "slot starts at this time (use 'now' to see shows immediately)")
    ap.add_argument("--channels", metavar="2-30,46", help="only these channel numbers")
    ap.add_argument("--short-movies", action="store_true",
                    help='cut movie blurbs to \'"Title" (year)\'')
    ap.add_argument("--keep-glyphs", action="store_true",
                    help="keep Prevue font icon bytes (0x80-0xBF, '|'); needs a latin-1 feeder")
    ap.add_argument("--no-premium-hilite", action="store_true",
                    help="don't red-highlight premium channels (header flag 0x40)")
    a = ap.parse_args()

    raw = a.curday.read_bytes()
    d = pp20_decrunch(raw) if raw[:4] == b"PP20" else raw
    chans = parse_curday(d)

    shift = int(a.shift_hours * 60)
    if a.start:
        # where the saved listings actually begin: the usual first slot of real channels
        # (all-day single-entry channels sit at slot 1 and would skew a plain min())
        firsts = sorted(c.programs[0].slot for c in chans
                        if c.number.isdigit() and len(c.programs) > 1)
        first = firsts[len(firsts) // 2] if firsts else 1
        if a.start == "now":
            n = dt.datetime.now()
            target = n.hour * 60 + (n.minute // 30) * 30
        else:
            hh, mm = a.start.split(":")
            target = int(hh) * 60 + int(mm)
        shift = target - (DAY_START_MIN + (first - 1) * SLOT_MIN)

    listings, notes = to_listings(chans, shift, a.keep_glyphs, a.short_movies,
                                  not a.no_premium_hilite,
                                  parse_range(a.channels) if a.channels else None)
    text = json.dumps(listings, indent=1, ensure_ascii=False)
    if a.out:
        a.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    progs = sum(len(c["schedule"]) for c in listings["channels"])
    print(f"{len(listings['channels'])} channels, {progs} programs, shift {shift/60:+.1f} h",
          file=sys.stderr)
    for n in notes:
        print("  note:", n, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
