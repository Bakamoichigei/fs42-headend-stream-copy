"""
listings.py - turn FS42 schedules into Prevue channel + program records.

Prevue thinks in half-hour timeslots within a 5 AM-to-5 AM "listings day".
For each station we look at what FS42 has scheduled at the start of every
timeslot and emit a program record whenever the programme changes, which is
how the real satellite feed described shows that span several timeslots.
"""

import datetime
import logging
import re

from fs42.liquid_api import LiquidAPI
from fs42.prevue import protocol as P

log = logging.getLogger("PrevueListings")


def source_id_for(station):
    """Prevue source identifiers are <= 6 upper-case characters and must be unique."""
    s = re.sub(r"[^A-Z0-9]", "", station["network_name"].upper())
    return (s or "CH%d" % int(station.get("channel_number", 0)))[:6]


def channel_record(station, overrides):
    num = int(station.get("channel_number", 0))
    o = overrides.get(str(num), {})
    flags = P.CH_NONE
    if o.get("hilite"):
        flags |= P.CH_HILITE
    if o.get("alt_hilite"):
        flags |= P.CH_ALT_HILITE
    return {
        "source_id": o.get("source_id", source_id_for(station))[:6],
        "number": o.get("number", str(num)),
        "call_letters": o.get("call_letters", station["network_name"])[:7],
        "flags": flags,
        "movie_channel": bool(o.get("movies", False)),
    }


def _blocks_for_day(station, day_start):
    day_end = day_start + datetime.timedelta(days=1)
    try:
        return LiquidAPI.get_blocks(station, str(day_start), str(day_end)) or []
    except Exception as e:                            # schedule DB missing, etc.
        log.warning(f"{station['network_name']}: no schedule for {day_start:%a %b %d} ({e})")
        return []


def programs_for_day(station, rec, day_start, movie_minutes=90):
    """[(timeslot, title, flags)] for one station's listings day starting at day_start (5 AM)."""
    blocks = sorted(_blocks_for_day(station, day_start), key=lambda b: b.start_time)
    out = []
    last_key = None
    for slot in range(1, 49):
        t = day_start + datetime.timedelta(minutes=30 * (slot - 1))
        blk = next((b for b in blocks if b.start_time <= t < b.end_time), None)
        if blk is None:
            key, title_ = None, None
        else:
            key, title_ = (blk.start_time, blk.title), (blk.title or "").strip()
        if key == last_key:
            continue
        last_key = key
        if blk is None:
            if out:                                     # close the previous show with a filler
                out.append((slot, "Off The Air", P.PG_NONE))
            continue
        flags = P.PG_NONE
        length_min = (blk.end_time - blk.start_time).total_seconds() / 60
        is_loop = type(blk).__name__ in ("LiquidLoopBlock", "LiquidOffAirBlock")
        if rec["movie_channel"] or (movie_minutes and length_min >= movie_minutes and not is_loop):
            flags |= P.PG_MOVIE
        out.append((slot, title_ or station["network_name"], flags))
    return out


def build(stations, overrides=None, now=None, days=2, exclude=(), movie_minutes=90):
    """Returns (julian_day_of_today, [channel records], {julian_day: [(slot, source_id, title, flags)]})."""
    overrides = overrides or {}
    now = now or datetime.datetime.now()
    today = P.listings_day_start(now)

    pairs = []
    seen = {}
    for st in sorted(stations, key=lambda s: int(s.get("channel_number", 0))):
        num = int(st.get("channel_number", 0))
        if num in exclude or not st.get("_has_schedule", True):
            continue
        rec = channel_record(st, overrides)
        sid = rec["source_id"]
        if sid in seen:                     # two stations that abbreviate the same way
            seen[sid] += 1
            rec["source_id"] = (sid[:5] + str(seen[sid]))[:6]
        else:
            seen[sid] = 0
        pairs.append((st, rec))

    progs = {}
    for st, rec in pairs:
        for d in range(days):
            day_start = today + datetime.timedelta(days=d)
            jd = P.julian_day(day_start)
            for slot, title_, flags in programs_for_day(st, rec, day_start, movie_minutes):
                progs.setdefault(jd, []).append((slot, rec["source_id"], title_, flags))
    return P.julian_day(today), [rec for _, rec in pairs], progs
