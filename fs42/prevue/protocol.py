"""
protocol.py - the UVSG satellite data protocol spoken by the Prevue Guide Amiga software.

A pure-Python port of the command encodings in Ari Weinstein's PrevueCLI
(https://github.com/AriX/PrevueCLI, BSD license), which reverse-engineered
the data feed Prevue boxes received over their serial port. Every encoder
here is checked byte-for-byte against PrevueCLI's own test fixtures
(test/test_prevue_protocol.py).

Framing of a data command:

    55 AA  <mode byte>  <payload ...>  <checksum = XOR of every preceding byte>

Times: listings are organised in "listings days" that start at 5 AM, split
into 48 half-hour timeslots (timeslot 1 = 5:00 AM). Days are identified by
the day-of-year modulo 256 (the "Julian day").
"""

import datetime

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

ALIGN_CENTER = 0x18      # ^X
ALIGN_LEFT = 0x19        # ^Y
ALIGN_RIGHT = 0x1A       # ^Z
_ALIGN = {None: None, "center": ALIGN_CENTER, "left": ALIGN_LEFT, "right": ALIGN_RIGHT}

# channel attribute flags
CH_NONE = 0x01
CH_HILITE = 0x02          # red highlight in grid
CH_SUMMARY_BY_SOURCE = 0x04
CH_NO_VIDEO_TAG = 0x08
CH_PPV = 0x10
CH_DITTO = 0x20
CH_ALT_HILITE = 0x40      # light blue highlight in grid
CH_STEREO = 0x80

# program attribute flags
PG_NONE = 0x01
PG_MOVIE = 0x02
PG_ALT_HILITE = 0x04
PG_TAG = 0x08
PG_SPORTS = 0x10
PG_REPEAT = 0x40

# local ad colours (Amiga only)
COLORS = {"transparent": 0x30, "white": 0x31, "black": 0x32, "yellow": 0x33,
          "red": 0x34, "lightBlue": 0x35, "light_blue": 0x35, "grey": 0x36, "blue": 0x37}

LISTINGS_DAY_START_HOUR = 5
BAUD = 2400


def checksum(data):
    c = 0
    for b in data:
        c ^= b
    return c


def frame(mode, payload=b""):
    body = bytes([0x55, 0xAA, mode]) + bytes(payload)
    return body + bytes([checksum(body)])


def _ascii(s):
    return s.encode("ascii", "replace")


def _latin1(s):
    return s.encode("latin-1", "replace")


def _yn(v):
    return b"Y" if v else b"N"


# ---------------------------------------------------------------------------
# time helpers
# ---------------------------------------------------------------------------

def listings_day_start(t):
    """Start (5 AM) of the listings day containing wall-clock time t."""
    d = t - datetime.timedelta(hours=LISTINGS_DAY_START_HOUR)
    return datetime.datetime(d.year, d.month, d.day, LISTINGS_DAY_START_HOUR)


def julian_day(t):
    """Day-of-year (mod 256) of the listings day containing t."""
    return listings_day_start(t).timetuple().tm_yday % 256


def timeslot(t):
    """1..48 - which half hour of its listings day t falls in."""
    minutes = (t - listings_day_start(t)).total_seconds() / 60
    return int(minutes // 30) + 1


# ---------------------------------------------------------------------------
# box control
# ---------------------------------------------------------------------------

def box_on(select_code="*"):
    """Start addressing boxes ("*" = every box)."""
    return frame(ord("A"), _ascii(select_code) + b"\x00")


def box_off():
    return frame(0xBB, b"\xBB\x00")


def reset():
    return frame(ord("R"), b"\x00")


def save_data():
    return frame(ord("%"), b"\x00")


def title(text, alignment=None):
    a = _ALIGN[alignment]
    return frame(ord("T"), (bytes([a]) if a else b"") + _ascii(text) + b"\x00")


def clock(t, dst=False):
    """Set the box clock. t is a naive wall-clock datetime."""
    dow = (t.weekday() + 1) % 7                      # Sunday = 0
    payload = bytes([dow, t.month - 1, t.day - 1, t.year - 1900,
                     t.hour, t.minute, t.second, 1 if dst else 0, 0])
    return frame(ord("K"), payload)


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------

def configuration(timeslots_back=1, timeslots_forward=4, scroll_speed=3, max_ad_count=36,
                  max_ad_lines=6, ignore_national_ads=False, ad_setting=0x0101, timezone=6,
                  observes_dst=True, cont=True, keyboard_active=False,
                  unknown2=False, unknown3=False, unknown4=True, unknown5=0x41,
                  grph=0x4E, video_insertion=0x4E, unknown6=0x00):
    """The 'F' configuration command. timezone is hours WEST of GMT (6 = Central)."""
    payload = (bytes([ord("A") + timeslots_back, ord("A") + timeslots_forward])
               + _ascii(str(scroll_speed)) + _ascii("%02d" % max_ad_count)
               + _ascii(str(max_ad_lines)) + _yn(ignore_national_ads)
               + ad_setting.to_bytes(2, "big") + _ascii(str(timezone))
               + _yn(observes_dst) + _yn(cont) + _yn(keyboard_active)
               + _yn(unknown2) + _yn(unknown3) + _yn(unknown4)
               + bytes([unknown5, grph, video_insertion, unknown6]) + b"\x00")
    return frame(ord("F"), payload)


def new_look_configuration(display_format="grid", text_ad_flag="S", clock_cmd=1):
    """The 'f' config.dat command.

    display_format: "grid" or "scroll" (the list format).
    clock_cmd: 1 or 2 for version 9 software; None for 7.8.3.
    Everything else is PrevueCLI's known-good template.
    """
    fmt = {"grid": "G", "scroll": "S"}[display_format]
    cfg = ("2C0108" "08" + fmt + "NAE01" "NNNNNN" "L" "2906" "YYY" "233606" "015" "1" "00"
           "YNYC").encode("ascii") + b"\x8E" + b"8" + text_ad_flag.encode("ascii") + b"NNNN"
    if clock_cmd is not None:
        cfg += str(clock_cmd).encode("ascii")
    cfg += b"\x00"
    return frame(ord("f"), b"\x00" + (len(cfg) + 1).to_bytes(2, "big") + cfg)


def dst(start, end, mode="local"):
    """Daylight saving boundaries from naive datetimes (day-of-year of the listings day)."""
    def parts(t):
        return (t.year, (t - datetime.timedelta(hours=LISTINGS_DAY_START_HOUR)).timetuple().tm_yday,
                t.hour, t.minute)
    return dst_raw(parts(start), parts(end), mode)


def dst_raw(start, end, mode="local"):
    """Same as dst() but with (year, day_of_year, hour, minute) tuples."""
    def b(x):
        return _ascii("%04d%03d%02d:%02d" % x)
    payload = b"\x04" + b(start) + b"\x13" + b(end) + b"\x00"
    m = {"local": b"2", "global": b"3"}[mode]
    return frame(ord("g"), m + _ascii("%02d" % len(payload)) + payload)


# ---------------------------------------------------------------------------
# local text ads (the crawl / ad panel)
# ---------------------------------------------------------------------------

def local_ads_reset():
    return frame(ord("L"), b"\x92\x00")


def local_ad(number, lines, time_period=None):
    """lines: list of (text, alignment) or plain strings. time_period: (first, last) timeslot."""
    payload = bytes([number])
    for line in lines:
        text, align = (line, None) if isinstance(line, str) else line
        a = _ALIGN[align]
        payload += (bytes([a]) if a else b"") + _ascii(text)
    if time_period:
        payload += bytes([0x14, time_period[0], time_period[1]])
    return frame(ord("L"), payload + b"\x00")


def color_local_ad(number, runs, time_period=None):
    """runs: list of (text, alignment, (background, foreground)) - colours by name, or None."""
    payload = bytes([number])
    for text, align, color in runs:
        a = _ALIGN[align]
        payload += bytes([a]) if a else b""
        if color:
            payload += bytes([0x03, COLORS[color[0]], COLORS[color[1]]])
        payload += _ascii(text)
    if time_period:
        payload += bytes([0x14, time_period[0], time_period[1]])
    return frame(ord("t"), payload + b"\x00")


# ---------------------------------------------------------------------------
# listings
# ---------------------------------------------------------------------------

def timeslot_mask(blacked_out):
    bits = [1] * 48
    for s in blacked_out:
        bits[s - 1] = 0
    return bytes(int("".join(str(b) for b in bits[i:i + 8]), 2) for i in range(0, 48, 8))


def channels(day, chans):
    """chans: list of dicts with source_id, number, call_letters, flags, blacked_out."""
    payload = bytes([day % 256])
    for c in chans:
        payload += bytes([0x12, c.get("flags", CH_NONE)]) + _ascii(c["source_id"][:6])
        if c.get("number") is not None:
            payload += b"\x11" + _ascii(str(c["number"]))
        if c.get("blacked_out") is not None:
            payload += b"\x14" + timeslot_mask(c["blacked_out"])
        if c.get("call_letters") is not None:
            payload += b"\x01" + _ascii(c["call_letters"][:7])
    return frame(ord("C"), payload + b"\x00")


def program(day, slot, source_id, name, flags=PG_NONE):
    payload = (bytes([slot, day % 256]) + _ascii(source_id[:6]) + b"\x12"
               + bytes([flags]) + _latin1(name) + b"\x00")
    return frame(ord("P"), payload)


def send_duration(data, baud=BAUD):
    """Seconds the bytes take on a real 8N1 serial line."""
    return len(data) * 10 / baud
