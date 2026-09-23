"""
schedule_cursor.py - "what should be on this channel at time T?"

A lightweight, per-station version of LiquidManager.get_play_point(). It
only ever loads the block(s) around the requested time instead of every
station's full schedule, so twelve channel processes don't each hold the
whole database in memory.
"""

import datetime
import logging
import os

from fs42.liquid_api import LiquidAPI

MIN_ITEM_S = 0.5    # ignore scheduled slivers shorter than this


class Item:
    """One thing to air: `path` from `in_s` for `dur_s` seconds (path None = nothing scheduled)."""

    def __init__(self, path, in_s, dur_s, ends_at, title="", content_type="", block_start=None, index=-1):
        self.path = path
        self.in_s = in_s
        self.dur_s = dur_s
        self.ends_at = ends_at
        self.title = title
        self.content_type = content_type
        self.key = (block_start, index)     # identifies the plan entry

    def __repr__(self):
        name = os.path.basename(self.path) if self.path else "<nothing>"
        return f"Item({name} in={self.in_s:.2f}s dur={self.dur_s:.2f}s '{self.title}' {self.content_type})"


class NoSchedule(Exception):
    pass


class ScheduleCursor:

    def __init__(self, station_conf, path_rewrite=None):
        self.station = station_conf
        self.name = station_conf["network_name"]
        self.path_rewrite = path_rewrite or []
        self._block = None
        self._l = logging.getLogger(f"Cursor[{self.name}]")

    def _load_block(self, when):
        lo = when - datetime.timedelta(seconds=1)
        hi = when + datetime.timedelta(seconds=1)
        blocks = LiquidAPI.get_blocks(self.station, str(lo), str(hi)) or []
        for b in blocks:
            if b.start_time <= when < b.end_time:
                return b
        return None

    def _map_path(self, path):
        for rule in self.path_rewrite:
            src, dst = rule.get("from", ""), rule.get("to", "")
            if src and path.startswith(src):
                path = dst + path[len(src):]
            ext = rule.get("ext")
            if ext:
                path = os.path.splitext(path)[0] + ext
        return path

    def at(self, when):
        """Returns the Item on air at `when`; raises NoSchedule if the schedule doesn't cover it."""
        b = self._block
        if b is None or not (b.start_time <= when < b.end_time):
            b = self._block = self._load_block(when)
        if b is None:
            raise NoSchedule(f"{self.name}: no schedule block at {when}")

        mark = b.start_time
        for i, entry in enumerate(b.plan or []):
            nxt = mark + datetime.timedelta(seconds=entry.duration)
            if nxt > when:
                offset = (when - mark).total_seconds()
                remaining = entry.duration - offset
                if remaining < MIN_ITEM_S:        # sliver - move on to the next entry
                    when = nxt
                    mark = nxt
                    continue
                if entry.is_stream or entry.media_type not in ("video", None):
                    path = None
                else:
                    path = self._map_path(entry.path)
                return Item(path, entry.skip + offset, remaining, nxt, b.title,
                            entry.content_type, b.start_time, i)
            mark = nxt

        # past the end of the block's plan: dead air until the block ends
        remaining = (b.end_time - when).total_seconds()
        if remaining < MIN_ITEM_S:
            return self.at(b.end_time)
        return Item(None, 0, remaining, b.end_time, b.title, "gap", b.start_time, -1)
