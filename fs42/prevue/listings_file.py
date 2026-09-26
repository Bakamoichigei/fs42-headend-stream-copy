"""
listings_file.py - a hand-written lineup for the Prevue feeder (no FS42 needed).

    python3 prevue_feed.py --listings mylineup.json --print
    python3 prevue_feed.py --listings mylineup.json --port 1234 --once

The file is JSON. See docs/prevue.md ("Hand-written listings") and
confs/examples/prevue_listings.json. In short:

{
  "channels": [
    { "number": 2, "call": "WFSA", "hilite": true,
      "schedule": { "05:00": "Early Today", "07:00": "Good Morning",
                    "19:00": "Wheel of Fortune", "20:00": {"title": "Big Movie", "movie": true} },
      "saturday": { "07:00": "Cartoon Express", "11:00": "Soul Train" } },
    { "number": 4, "call": "KMOV", "movies": true,
      "loop": [[120, "Back to the Future"], [90, "The Goonies"]] }
  ]
}

"schedule" lists start times (24-hour, local) for every day; each show runs until the next
start. A weekday key ("monday" .. "sunday") replaces "schedule" for that day. Days are
broadcast days, 5 AM to 5 AM, so "saturday": {"01:00": ...} is late Saturday night. "loop" instead repeats [minutes, title] pairs from 5 AM, the start of
Prevue's listings day.
"""

import datetime
import json
import re

from fs42.prevue import protocol as P

# attribute bits from the satellite data protocol; which colours 9.0.4 draws for each is
# still being mapped (see confs/examples/prevue_flag_test.json)
PROGRAM_FLAGS = {"movie": P.PG_MOVIE, "sports": P.PG_SPORTS, "alt_hilite": P.PG_ALT_HILITE,
                 "tag": P.PG_TAG, "repeat": P.PG_REPEAT}
CHANNEL_FLAGS = {"hilite": P.CH_HILITE, "alt_hilite": P.CH_ALT_HILITE, "ppv": P.CH_PPV,
                 "stereo": P.CH_STEREO, "no_video_tag": P.CH_NO_VIDEO_TAG}

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class ListingsError(ValueError):
    pass


def _entry(value, where):
    """A title string, or {"title": ..., "movie": bool, "sports": bool}."""
    if isinstance(value, str):
        return value, P.PG_NONE
    if isinstance(value, dict) and isinstance(value.get("title"), str):
        flags = P.PG_NONE
        for key, bit in PROGRAM_FLAGS.items():
            if value.get(key):
                flags |= bit
        return value["title"], flags
    raise ListingsError(f"{where}: expected a title or {{\"title\": ...}}, got {value!r}")


def _clock(text, where):
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(text).strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ListingsError(f"{where}: start time {text!r} should look like \"19:30\"")
    return int(m.group(1)), int(m.group(2))


def _events(ch, name, day_start):
    """(start datetime, title, flags) covering the 24 h from day_start, plus the show already on."""
    events = []
    if "loop" in ch:
        loop = ch["loop"]
        if not loop:
            raise ListingsError(f"{name}: \"loop\" is empty")
        t, i = day_start, 0
        while t < day_start + datetime.timedelta(days=1):
            item = loop[i % len(loop)]
            if not (isinstance(item, (list, tuple)) and len(item) == 2 and isinstance(item[0], (int, float))
                    and item[0] > 0):
                raise ListingsError(f"{name}: each \"loop\" item should be [minutes, title], got {item!r}")
            title, flags = _entry(item[1], name)
            events.append((t, title, flags))
            t += datetime.timedelta(minutes=item[0])
            i += 1
        return events
    if "schedule" not in ch and not any(d in ch for d in DAYS):
        raise ListingsError(f"{name}: needs a \"schedule\", weekday schedules, or a \"loop\"")
    # Weekday keys mean the *broadcast day*, 5 AM to 5 AM, the way TV people and Prevue count
    # it: "saturday": {"01:00": ...} is late Saturday night. Include the previous day too,
    # for the show already running at 5 AM.
    for offset in (-1, 0):
        lday = day_start + datetime.timedelta(days=offset)
        sched = ch.get(DAYS[lday.weekday()], ch.get("schedule", {}))
        if not isinstance(sched, dict):
            raise ListingsError(f"{name}: a schedule should be {{\"HH:MM\": title, ...}}")
        for clock, value in sched.items():
            hh, mm = _clock(clock, name)
            title, flags = _entry(value, f"{name} {clock}")
            t = lday.replace(hour=hh, minute=mm)
            if hh < P.LISTINGS_DAY_START_HOUR:          # 00:00-04:59 is the end of this broadcast day
                t += datetime.timedelta(days=1)
            events.append((t, title, flags))
    return sorted(events, key=lambda e: e[0])


def _programs(ch, name, day_start, all_movies):
    """[(slot, title, flags)]: a record for each half-hour slot where the show changes."""
    events = _events(ch, name, day_start)
    out, last = [], None
    for slot in range(1, 49):
        t = day_start + datetime.timedelta(minutes=30 * (slot - 1))
        on = [e for e in events if e[0] <= t]
        if not on:
            continue
        start, title, flags = on[-1]
        if (start, title) == last:
            continue
        last = (start, title)
        if all_movies:
            flags |= P.PG_MOVIE
        out.append((slot, title, flags))
    return out


def load(path, now=None, days=2):
    """Returns (julian_day_of_today, [channel records], {julian_day: [(slot, source_id, title, flags)]})."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ListingsError(f"{path} isn't valid JSON: {e}")
    chans_in = data.get("channels") if isinstance(data, dict) else None
    if not isinstance(chans_in, list) or not chans_in:
        raise ListingsError(f"{path}: expected {{\"channels\": [ ... ]}}")

    now = now or datetime.datetime.now()
    today = P.listings_day_start(now)
    chans, progs, seen = [], {}, {}
    for i, ch in enumerate(sorted(chans_in, key=lambda c: int(c.get("number", 0)))):
        if "number" not in ch or "call" not in ch:
            raise ListingsError(f"channel #{i + 1}: needs \"number\" and \"call\"")
        name = f"channel {ch['number']} ({ch['call']})"
        sid = re.sub(r"[^A-Z0-9]", "", str(ch.get("source", ch["call"])).upper())[:6] or f"CH{ch['number']}"
        if sid in seen:                                   # keep source ids unique
            seen[sid] += 1
            sid = (sid[:5] + str(seen[sid]))[:6]
        else:
            seen[sid] = 0
        flags = P.CH_NONE
        for key, bit in CHANNEL_FLAGS.items():
            if ch.get(key):
                flags |= bit
        chans.append({"source_id": sid, "number": str(ch["number"]), "call_letters": str(ch["call"])[:7],
                      "flags": flags})
        for d in range(days):
            day_start = today + datetime.timedelta(days=d)
            jd = P.julian_day(day_start)
            for slot, title, pflags in _programs(ch, name, day_start, bool(ch.get("movies"))):
                progs.setdefault(jd, []).append((slot, sid, title, pflags))
    return P.julian_day(today), chans, progs
