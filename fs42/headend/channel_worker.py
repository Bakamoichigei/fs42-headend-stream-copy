"""
channel_worker.py - the playout loop for ONE channel (runs in its own process).

    loop:
        t    = wall-clock time the next packet will air (+ decoder latency)
        item = schedule[t]
        splice item's file into the channel's transport stream

Because each lookup is keyed to the output's own clock, small errors
(keyframe-aligned in-points, a file a few frames short) never accumulate:
every splice re-anchors to the schedule.
"""

import datetime
import json
import logging
import os
import signal
import time

from fs42.headend.schedule_cursor import ScheduleCursor, NoSchedule
from fs42.headend.ts_splicer import TSChannelOutput

STATUS_DIR = "runtime/headend"


def _write_status(num, data):
    try:
        os.makedirs(STATUS_DIR, exist_ok=True)
        path = os.path.join(STATUS_DIR, f"ch{num:02d}.json")
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=1, default=str)
        os.replace(tmp, path)
    except OSError:
        pass


class ChannelWorker:

    def __init__(self, station, hconf, url, stop_event=None, schedule_lock=None,
                 realtime=True, start_wall=None, run_seconds=None):
        self.station = station
        self.name = station["network_name"]
        self.num = int(station.get("channel_number", 0))
        self.hconf = hconf
        self.url = url
        self.stop_event = stop_event
        self.lock = schedule_lock
        self.run_seconds = run_seconds
        self.lead = datetime.timedelta(seconds=float(hconf.get("schedule_lead_s", 0.7)))
        self.slate = hconf.get("slate_file")
        if self.slate and not os.path.exists(self.slate):
            self.slate = None
        self.auto_extend = hconf.get("auto_extend_schedule", True)
        self._last_extend = 0.0
        self._last_nosched_log = 0.0
        self.log = logging.getLogger(f"CH{self.num:02d}:{self.name}")
        self.out = TSChannelOutput(url, service_name=self.name[:40], tsid=self.num or 1,
                                   provider=hconf.get("provider_name", "FS42"),
                                   realtime=realtime, start_wall=start_wall, log=self.log)
        self.cursor = ScheduleCursor(station, hconf.get("path_rewrite"))
        if stop_event is not None:
            self.out.should_stop = stop_event.is_set
        self.status = {"channel": self.num, "network": self.name, "url": url, "splices": 0,
                       "errors": 0, "fills": 0, "started": datetime.datetime.now()}

    # ------------------------------------------------------------------

    def _stopping(self, t_start):
        if self.stop_event is not None and self.stop_event.is_set():
            return True
        if self.run_seconds is not None and self.out.clock is not None:
            return self.out.air_time() >= t_start + datetime.timedelta(seconds=self.run_seconds)
        return False

    def fill(self, seconds, why):
        """Cover `seconds` with the slate (bars & tone) or, failing that, an empty mux."""
        self.status["fills"] += 1
        self.log.info(f"fill {seconds:.1f}s ({why})")
        left = seconds
        if self.slate:
            while left > 0.5 and not (self.stop_event and self.stop_event.is_set()):
                r = self.out.splice(self.slate, 0, left)
                if not r.ok or r.aired_s < 0.1:
                    break
                left -= r.aired_s
        if left > 0.05:
            self.out.gap(left)

    def _try_extend(self):
        """Returns True if the schedule was extended (caller should retry right away)."""
        if not self.auto_extend or time.time() - self._last_extend < 600:
            return False
        self._last_extend = time.time()
        self.log.warning("schedule exhausted - extending by one day")
        try:
            from fs42.liquid_schedule import LiquidSchedule
            if self.lock:
                self.lock.acquire()
            try:
                LiquidSchedule(self.station).add_days(1)
            finally:
                if self.lock:
                    self.lock.release()
            return True
        except Exception as e:
            self.log.error(f"schedule extension failed: {e}")
            return False

    def run(self):
        self.log.info(f"on air -> {self.url}")
        t_start = self.out.air_time()
        last_key, last_eof = None, False
        while not self._stopping(t_start):
            when = self.out.air_time() + self.lead
            try:
                item = self.cursor.at(when)
            except NoSchedule as e:
                if time.time() - self._last_nosched_log > 60:
                    self.log.error(str(e))
                    self._last_nosched_log = time.time()
                if self._try_extend():
                    continue
                self.fill(10, "no schedule")
                continue
            except Exception as e:
                self.log.exception(f"schedule lookup failed: {e}")
                self.status["errors"] += 1
                self.fill(5, "schedule error")
                continue

            if item.path is None:
                self.fill(min(item.dur_s, 30), f"nothing scheduled ({item.content_type})")
                continue
            if item.key == last_key and last_eof:
                # we already played this entry to EOF: the file is shorter than the schedule thinks
                self.fill(min(item.dur_s, 30), "file shorter than scheduled")
                continue
            if not os.path.exists(item.path):
                self.log.error(f"missing file: {item.path}")
                self.status["errors"] += 1
                self.fill(min(item.dur_s, 30), "missing file")
                continue

            self.status.update(now_playing=item.path, title=item.title, content_type=item.content_type,
                               in_s=round(item.in_s, 2), dur_s=round(item.dur_s, 2),
                               ends_at=item.ends_at, updated=datetime.datetime.now(),
                               stalls=self.out.pacer.stalls)
            _write_status(self.num, self.status)
            self.log.info(f"{when:%H:%M:%S} {item}")

            res = self.out.splice(item.path, item.in_s, item.dur_s)
            self.status["splices"] += 1
            if not res.ok:
                self.log.warning(f"splice failed for {item.path}: {res.reason}")
                self.status["errors"] += 1
                self.fill(min(item.dur_s, 30), res.reason)
            elif res.aired_s < 0.1:
                self.fill(min(item.dur_s, 1.0), "nothing aired")
            last_key, last_eof = item.key, res.eof

        self.out.close()
        self.log.info("off air")


def channel_main(station, hconf, url, stop_event, schedule_lock, realtime=True,
                 start_wall=None, run_seconds=None, log_level=logging.INFO):
    """multiprocessing entry point."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)     # the supervisor owns shutdown
    logging.basicConfig(format="%(asctime)s %(levelname)s:%(name)s:%(message)s", level=log_level)
    try:
        os.nice(-5)
    except OSError:
        pass
    ChannelWorker(station, hconf, url, stop_event, schedule_lock, realtime,
                  start_wall, run_seconds).run()
