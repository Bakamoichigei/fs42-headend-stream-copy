"""
ts_splicer.py - seamless stream-copy MPEG-TS playout for the FS42 headend.

One TSChannelOutput is one continuous transport stream (one "channel").
You hand it files + in/out points with splice(); it reads the TS packets
straight off disk and forwards them without touching the elementary
streams. Only transport-layer fields are rewritten:

  * PTS / DTS / PCR are shifted so the output timeline never jumps
  * PIDs are remapped to a fixed output layout
  * continuity counters are regenerated per output PID
  * PAT / PMT / SDT are regenerated at a fixed interval

Packets leave at the rate implied by the (rewritten) PCR, so the output is
paced like a real encoder/multiplexer and the decoder's clock recovery
never sees a discontinuity across file boundaries.

The only requirement is that every file on a channel shares the same codec
parameters and has closed GOPs (see tools/headend_prep.sh). PID values in
the source files don't matter - they're read from each file's PMT.

Pure standard library, no external dependencies.
"""

import datetime
import logging
import os
import random
import socket
import struct
import time
import urllib.parse

TS = 188
CLK = 27_000_000              # PCR clock
PTS_HZ = 90_000
PTS_MOD = 1 << 33
PCR_MOD = PTS_MOD * 300
NULL_PID = 0x1FFF

OUT_PMT_PID = 0x1000
OUT_VIDEO_PID = 0x100         # also the PCR PID
OUT_AUDIO_PID = 0x101
SDT_PID = 0x11

VIDEO_TYPES = {0x01, 0x02, 0x10, 0x1B, 0x24}
AUDIO_TYPES = {0x03, 0x04, 0x0F, 0x11, 0x81, 0x87}

PCR_INTERVAL = CLK * 30 // 1000     # synthetic PCR if none seen for 30 ms
PSI_INTERVAL = CLK * 100 // 1000    # PAT/PMT every 100 ms
SDT_INTERVAL = CLK * 1              # SDT every second
PKTS_PER_DGRAM = 7                  # 7 * 188 = 1316 bytes, fits a 1500 MTU


# --------------------------------------------------------------------------
# low-level helpers
# --------------------------------------------------------------------------

def _crc32_table():
    table = []
    for i in range(256):
        c = i << 24
        for _ in range(8):
            c = ((c << 1) ^ 0x04C11DB7) if (c & 0x80000000) else (c << 1)
        table.append(c & 0xFFFFFFFF)
    return table


_CRC_TABLE = _crc32_table()


def crc32_mpeg(data):
    crc = 0xFFFFFFFF
    for b in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _CRC_TABLE[((crc >> 24) ^ b) & 0xFF]
    return crc


def read_ts(b, i):
    return (((b[i] >> 1) & 0x07) << 30) | (b[i + 1] << 22) | ((b[i + 2] >> 1) << 15) \
        | (b[i + 3] << 7) | (b[i + 4] >> 1)


def write_ts(b, i, v):
    v %= PTS_MOD
    b[i] = (b[i] & 0xF0) | ((v >> 29) & 0x0E) | 0x01
    b[i + 1] = (v >> 22) & 0xFF
    b[i + 2] = ((v >> 14) & 0xFE) | 0x01
    b[i + 3] = (v >> 7) & 0xFF
    b[i + 4] = ((v << 1) & 0xFE) | 0x01


def read_pcr(b, i):
    base = (b[i] << 25) | (b[i + 1] << 17) | (b[i + 2] << 9) | (b[i + 3] << 1) | (b[i + 4] >> 7)
    ext = ((b[i + 4] & 0x01) << 8) | b[i + 5]
    return base * 300 + ext


def write_pcr(b, i, v):
    v %= PCR_MOD
    base, ext = divmod(v, 300)
    b[i] = (base >> 25) & 0xFF
    b[i + 1] = (base >> 17) & 0xFF
    b[i + 2] = (base >> 9) & 0xFF
    b[i + 3] = (base >> 1) & 0xFF
    b[i + 4] = ((base & 1) << 7) | 0x7E | ((ext >> 8) & 1)
    b[i + 5] = ext & 0xFF


class Pkt:
    """Parsed view of one 188-byte packet (offsets into a shared buffer)."""
    __slots__ = ("pid", "pusi", "afc", "payload", "pcr_at", "rai")

    def __init__(self, buf, o):
        b1 = buf[o + 1]
        self.pid = ((b1 & 0x1F) << 8) | buf[o + 2]
        self.pusi = bool(b1 & 0x40)
        self.afc = (buf[o + 3] >> 4) & 0x03
        self.pcr_at = -1
        self.rai = False
        p = o + 4
        if self.afc & 0x02:
            af_len = buf[p]
            if af_len > 0:
                flags = buf[p + 1]
                self.rai = bool(flags & 0x40)
                if flags & 0x10 and af_len >= 7:
                    self.pcr_at = p + 2
            p += 1 + af_len
        self.payload = p if (self.afc & 0x01) and p < o + TS else -1


def pes_timestamps(buf, p, end):
    """Returns (pts, dts, pts_at, dts_at) for a PES header at buf[p]; -1 when absent."""
    if p < 0 or p + 9 > end or buf[p] != 0 or buf[p + 1] != 0 or buf[p + 2] != 1:
        return -1, -1, -1, -1
    sid = buf[p + 3]
    if sid in (0xBC, 0xBE, 0xBF, 0xF0, 0xF1, 0xFF, 0xF2, 0xF8):
        return -1, -1, -1, -1
    flags = buf[p + 7] >> 6
    pts = dts = pts_at = dts_at = -1
    if flags & 0x02 and p + 14 <= end:
        pts_at = p + 9
        pts = read_ts(buf, pts_at)
        dts = pts
        if flags == 0x03 and p + 19 <= end:
            dts_at = p + 14
            dts = read_ts(buf, dts_at)
    return pts, dts, pts_at, dts_at


def is_keyframe(buf, pkt, o, stream_type):
    if pkt.rai:
        return True
    if pkt.payload < 0:
        return False
    chunk = bytes(buf[pkt.payload:o + TS])
    if stream_type in (0x01, 0x02):
        # sequence header or GOP header -> start of a (closed) GOP
        return b"\x00\x00\x01\xb3" in chunk or b"\x00\x00\x01\xb8" in chunk
    if stream_type == 0x1B:
        i = chunk.find(b"\x00\x00\x01", 4)
        while i >= 0 and i + 3 < len(chunk):
            if chunk[i + 3] & 0x1F in (5, 7):
                return True
            i = chunk.find(b"\x00\x00\x01", i + 3)
    return False


def _section_packet(pid, cc, section):
    body = bytes([0x00]) + section                      # pointer_field
    body += b"\xFF" * (184 - len(body))
    return bytes([0x47, 0x40 | (pid >> 8), pid & 0xFF, 0x10 | (cc & 0x0F)]) + body


def _section(table_id, ext_id, version, payload):
    length = 5 + len(payload) + 4
    hdr = bytes([table_id, 0xB0 | ((length >> 8) & 0x0F), length & 0xFF,
                 ext_id >> 8, ext_id & 0xFF, 0xC1 | ((version & 0x1F) << 1), 0x00, 0x00])
    sec = hdr + payload
    return sec + struct.pack(">I", crc32_mpeg(sec))


def build_pat(tsid, program, pmt_pid):
    return _section(0x00, tsid, 0, struct.pack(">HH", program, 0xE000 | pmt_pid))


def build_pmt(program, pcr_pid, streams):
    body = struct.pack(">HH", 0xE000 | pcr_pid, 0xF000)
    for stype, pid, es_info in streams:
        body += struct.pack(">BHH", stype, 0xE000 | pid, 0xF000 | len(es_info)) + es_info
    return _section(0x02, program, 0, body)


def build_sdt(tsid, program, provider, name):
    provider = provider.encode("latin-1", "replace")[:40]
    name = name.encode("latin-1", "replace")[:40]
    desc = bytes([0x48, 3 + len(provider) + len(name), 0x01, len(provider)]) + provider \
        + bytes([len(name)]) + name
    svc = struct.pack(">HBH", program, 0xFC, 0x8000 | len(desc)) + desc
    body = struct.pack(">HB", 1, 0xFF) + svc                        # original_network_id
    return _section(0x42, tsid, 0, body)


def parse_psi(path, max_packets=4000):
    """Find the first program's PMT in a file -> (pcr_pid, [(type, pid, es_info), ...])."""
    with open(path, "rb") as f:
        data = bytearray(f.read(TS * max_packets))
    pmt_pid = None
    for o in range(0, len(data) - TS + 1, TS):
        if data[o] != 0x47:
            continue
        pk = Pkt(data, o)
        if not pk.pusi or pk.payload < 0:
            continue
        p = pk.payload + 1 + data[pk.payload]           # skip pointer field
        if pk.pid == 0 and pmt_pid is None:
            slen = ((data[p + 1] & 0x0F) << 8) | data[p + 2]
            q, end = p + 8, p + 3 + slen - 4
            while q + 4 <= end:
                prog = (data[q] << 8) | data[q + 1]
                pid = ((data[q + 2] & 0x1F) << 8) | data[q + 3]
                if prog != 0:
                    pmt_pid = pid
                    break
                q += 4
        elif pmt_pid is not None and pk.pid == pmt_pid and data[p] == 0x02:
            slen = ((data[p + 1] & 0x0F) << 8) | data[p + 2]
            end = p + 3 + slen - 4
            pcr_pid = ((data[p + 8] & 0x1F) << 8) | data[p + 9]
            pinfo = ((data[p + 10] & 0x0F) << 8) | data[p + 11]
            q = p + 12 + pinfo
            streams = []
            while q + 5 <= end:
                stype = data[q]
                pid = ((data[q + 1] & 0x1F) << 8) | data[q + 2]
                ilen = ((data[q + 3] & 0x0F) << 8) | data[q + 4]
                streams.append((stype, pid, bytes(data[q + 5:q + 5 + ilen])))
                q += 5 + ilen
            return pcr_pid, streams
    raise ValueError(f"no PAT/PMT found in first {max_packets} packets of {path}")


# --------------------------------------------------------------------------
# output side: sinks + pacing
# --------------------------------------------------------------------------

class UdpSink:
    """udp://239.42.0.3:5000?ttl=4&iface=192.168.1.10   (rtp://... adds RTP headers)"""

    def __init__(self, url):
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        self.addr = (u.hostname, u.port or 5000)
        self.rtp = u.scheme == "rtp"
        self.seq = random.randint(0, 0xFFFF)
        self.ssrc = random.getrandbits(32)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1 << 20)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, int(q.get("ttl", 4)))
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, int(q.get("loop", 1)))
        if q.get("iface"):
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(q["iface"]))
        if q.get("tos"):
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, int(q["tos"], 0))

    def send(self, payload, clock27):
        if self.rtp:
            hdr = struct.pack(">BBHII", 0x80, 33, self.seq, (clock27 // 300) & 0xFFFFFFFF, self.ssrc)
            self.seq = (self.seq + 1) & 0xFFFF
            payload = hdr + payload
        try:
            self.sock.sendto(payload, self.addr)
        except OSError as e:          # e.g. network briefly down - keep the clock running
            logging.getLogger("UdpSink").warning(f"send failed: {e}")

    def close(self):
        self.sock.close()


class FileSink:
    """file:///path/out.ts - handy for testing and off-air checks."""

    def __init__(self, url):
        self.f = open(urllib.parse.urlparse(url).path, "wb")

    def send(self, payload, clock27):
        self.f.write(payload)

    def close(self):
        self.f.close()


def open_sink(url):
    if url.startswith(("udp://", "rtp://")):
        return UdpSink(url)
    if url.startswith("file://"):
        return FileSink(url)
    raise ValueError(f"unsupported output url {url}")


class Pacer:
    """Maps the 27 MHz output clock onto the wall clock."""

    def __init__(self, realtime=True, max_lag_s=1.0, log=None):
        self.realtime = realtime
        self.max_lag = max_lag_s
        self.t0 = None
        self.c0 = None
        self.w0 = None
        self.log = log or logging.getLogger("Pacer")
        self.stalls = 0

    def anchor(self, clock27, wall=None):
        self.t0 = time.monotonic()
        self.w0 = wall or datetime.datetime.now()
        self.c0 = clock27

    def target(self, clock27):
        return self.t0 + (clock27 - self.c0) / CLK

    def wait_until(self, clock27):
        if not self.realtime:
            return
        tgt = self.target(clock27)
        now = time.monotonic()
        ahead = tgt - now
        if ahead > 0.002:
            time.sleep(ahead)
        elif -ahead > self.max_lag:
            # fell behind (slow disk / NAS hiccup): slide the anchor instead of
            # bursting to catch up, which would overflow the decoder's buffer
            self.t0 += -ahead
            self.stalls += 1
            self.log.warning(f"output stalled {-ahead:.2f}s - re-anchoring clock")

    def wall(self, clock27):
        if self.t0 is None:
            return datetime.datetime.now()
        if not self.realtime:
            return self.w0 + datetime.timedelta(seconds=(clock27 - self.c0) / CLK)
        mono = self.target(clock27)
        return datetime.datetime.now() + datetime.timedelta(seconds=mono - time.monotonic())


# --------------------------------------------------------------------------
# the channel
# --------------------------------------------------------------------------

class SpliceResult:
    def __init__(self):
        self.ok = False
        self.aired_s = 0.0
        self.video_pkts = 0
        self.audio_pkts = 0
        self.start_error_s = 0.0    # keyframe start vs requested in-point (+ = late)
        self.eof = False
        self.reason = ""

    def __repr__(self):
        return (f"SpliceResult(ok={self.ok} aired={self.aired_s:.2f}s v={self.video_pkts} "
                f"a={self.audio_pkts} start_err={self.start_error_s:+.3f}s eof={self.eof} {self.reason})")


class TSChannelOutput:

    def __init__(self, url, service_name="FS42", tsid=1, provider="FS42", realtime=True,
                 start_wall=None, log=None):
        self.log = log or logging.getLogger(f"TS[{service_name}]")
        self.sink = open_sink(url)
        self.pacer = Pacer(realtime=realtime, log=self.log)
        self.start_wall = start_wall
        self.service_name = service_name
        self.provider = provider
        self.tsid = tsid & 0xFFFF
        self.program = 1

        self.clock = None                 # 27 MHz output clock (unwrapped)
        self.last_pcr_out = None
        self.next_psi = 0
        self.next_sdt = 0
        self.cc = {}
        self.dgram = bytearray()
        self.dgram_clock = 0
        self.dgram_n = 0

        self.v_type = None                # output ES layout, fixed by the first file
        self.a_type = None
        self.v_info = b""
        self.a_info = b""
        self.last_v_pts = None            # last displayed picture, unwrapped 90 kHz output timeline
        self.v_frame = 3003
        self.last_a_pts = None
        self.a_frame = 2160               # MP2 @ 48k = 1152 samples = 2160 ticks
        self.bitrate = 7_000_000
        self.should_stop = None           # optional callable; checked every chunk

    # ---- public -----------------------------------------------------------

    def air_time(self):
        """Wall-clock time at which the next packet will leave."""
        if self.clock is None:
            return self.start_wall or datetime.datetime.now()
        return self.pacer.wall(self.clock)

    def close(self):
        self._flush()
        self.sink.close()

    def gap(self, seconds):
        """Keep the mux alive (PSI + PCR + null packets) with no picture."""
        if self.clock is None:
            self._start_clock(10 * CLK)
        end = self.clock + int(seconds * CLK)
        null = bytes([0x47, 0x1F, 0xFF, 0x10]) + b"\xFF" * 184
        step = CLK // 100
        while self.clock < end:
            if self.should_stop is not None and self.should_stop():
                break
            self._housekeeping()
            self._emit(null)
            self.clock += step
        self._housekeeping()
        return seconds

    def splice(self, path, in_s=0.0, dur_s=None):
        """Air `dur_s` seconds of `path` starting at `in_s` (seconds into the file).

        Returns a SpliceResult. aired_s is measured on the output clock, so the
        caller can simply advance its schedule position by it.
        """
        res = SpliceResult()
        try:
            pcr_pid, streams = parse_psi(path)
        except (OSError, ValueError) as e:
            res.reason = f"unreadable: {e}"
            return res

        vid = next(((t, p, i) for t, p, i in streams if t in VIDEO_TYPES), None)
        aud = next(((t, p, i) for t, p, i in streams if t in AUDIO_TYPES), None)
        if aud is None:   # DVB-style AC-3 (stream_type 6 + AC-3 descriptor)
            aud = next(((t, p, i) for t, p, i in streams if t == 0x06 and (b"\x6a" in i[:1] or b"AC-3" in i)), None)
        if vid is None:
            res.reason = "no video stream"
            return res
        if self.v_type is None:
            self.v_type, self.v_info = vid[0], vid[2]
            if aud:
                self.a_type, self.a_info = aud[0], aud[2]
            self.log.info(f"output layout: video type 0x{self.v_type:02x}"
                          + (f", audio type 0x{self.a_type:02x}" if aud else ", no audio"))
        elif vid[0] != self.v_type or (aud and self.a_type is not None and aud[0] != self.a_type):
            self.log.warning(f"{os.path.basename(path)}: codec layout differs from the channel's "
                             f"(re-encode it with headend_prep.sh) - airing anyway")
        v_pid, a_pid = vid[1], (aud[1] if aud else -1)

        size = os.path.getsize(path)
        with open(path, "rb", buffering=0) as f:
            first_pts = self._first_video_pts(f, v_pid, 0)
            if first_pts is None:
                res.reason = "no video PTS"
                return res
            self._estimate_bitrate(f, pcr_pid)
            target = first_pts + int(max(0.0, in_s) * PTS_HZ)
            end_in = target + int(dur_s * PTS_HZ) if dur_s else None
            pos = self._seek(f, v_pid, target - PTS_HZ, size) if in_s > 1.5 else 0
            last_v_off = self._last_pid_offset(f, v_pid, size)
            f.seek(pos)
            self._run(f, res, v_pid, a_pid, pcr_pid, target, end_in, in_s, pos, last_v_off)
        return res

    # ---- internals ----------------------------------------------------------

    def _start_clock(self, clock27):
        self.clock = clock27
        self.pacer.anchor(clock27, self.start_wall)
        self.next_psi = clock27
        self.next_sdt = clock27

    def _run(self, f, res, v_pid, a_pid, pcr_pid, target, end_in, in_s, file_off, last_v_off):
        started = False
        off90 = off27 = 0
        seg_clock0 = None
        last_pcr_in = None
        bytes_since_pcr = 0
        v_done = False
        a_done = a_pid < 0
        a_pass = False
        v_pass = False
        a_floor = None
        max_v_pts = self.last_v_pts
        a_end = end_in
        max_a_pts = self.last_a_pts
        prev_v_dts_in = None
        tail_limit = 0
        tail_bytes = 0
        CHUNK = TS * 2048
        tol = PTS_HZ // 4
        tick = 188 * 8 * CLK

        while True:
            if self.should_stop is not None and self.should_stop():
                res.reason = "stopped"
                break
            buf = f.read(CHUNK)
            if not buf:
                res.eof = True
                break
            buf = bytearray(buf)
            chunk_off = file_off
            file_off += len(buf)
            n = len(buf) - len(buf) % TS
            o = 0
            while o < n:
                if buf[o] != 0x47:       # lost sync - hunt for it
                    o += 1
                    continue
                pk = Pkt(buf, o)
                pid = pk.pid

                # ---- input clock bookkeeping --------------------------------
                if pid == pcr_pid and pk.pcr_at >= 0:
                    pcr_in = read_pcr(buf, pk.pcr_at)
                    if last_pcr_in is not None and bytes_since_pcr and pcr_in > last_pcr_in:
                        br = bytes_since_pcr * 8 * CLK // (pcr_in - last_pcr_in)
                        if 500_000 < br < 40_000_000:
                            self.bitrate = (self.bitrate * 7 + br) // 8
                    last_pcr_in = pcr_in
                    bytes_since_pcr = 0
                bytes_since_pcr += TS

                if not started:
                    # hunt for the first usable keyframe at/after the in-point
                    if pid == v_pid and pk.pusi:
                        pts, dts, _, _ = pes_timestamps(buf, pk.payload, o + TS)
                        if pts >= 0 and (in_s <= 0.25 or pts >= target - tol) \
                                and is_keyframe(buf, pk, o, self.v_type):
                            started = True
                            v_pass = True
                            dts0 = dts
                            if last_pcr_in is not None:
                                pcr_here = last_pcr_in + (bytes_since_pcr - TS) * 8 * CLK // self.bitrate
                            else:
                                pcr_here = dts0 * 300 - int(0.7 * CLK)
                            if self.clock is None:
                                off90 = 10 * PTS_HZ - dts0
                                self._start_clock(pcr_here + off90 * 300)
                            else:
                                need_clock = -(-(self.clock - pcr_here) // 300)
                                # first new picture displays one frame after the last old one
                                need_cont = (self.last_v_pts + self.v_frame - pts) \
                                    if self.last_v_pts is not None else need_clock
                                off90 = max(need_clock, need_cont)
                            off27 = off90 * 300
                            seg_clock0 = self.clock
                            a_floor = pts                      # first displayed picture
                            if self.last_a_pts is not None:
                                a_floor = max(a_floor, self.last_a_pts + self.a_frame - 90 - off90)  # no overlap
                            res.start_error_s = (pts - target) / PTS_HZ if in_s > 0.25 else 0.0
                    if not started:
                        o += TS
                        continue

                # ---- output clock: follow the input's (shifted) PCR timeline -----
                if v_done:
                    # audio tail after the video out-point: forward it without
                    # advancing the clock (a ~100-200 ms audio burst), so the next
                    # file's video can butt straight up against this one
                    tail_bytes += TS
                elif pid == pcr_pid and pk.pcr_at >= 0:
                    # re-lock to the source PCR (never free-run on our bitrate estimate)
                    self.clock = read_pcr(buf, pk.pcr_at) + off27
                else:
                    self.clock += tick // self.bitrate

                out_pid = None
                if pid == v_pid:
                    if pk.pusi:
                        pts, dts, pts_at, dts_at = pes_timestamps(buf, pk.payload, o + TS)
                        if dts >= 0:
                            # cut in front of the first picture that displays at/after the
                            # out-point. That's always an I/P frame, so every B-frame we've
                            # already sent is complete and the display order stays clean.
                            if end_in is not None and pts >= end_in and not v_done:
                                v_done = True
                                if max_v_pts is not None:
                                    a_end = max_v_pts - off90 + self.v_frame
                                tail_limit = self.bitrate // 8 * 2      # bytes: ~2 s of mux
                            v_pass = not v_done
                            if v_pass:
                                if prev_v_dts_in is not None and 0 < dts - prev_v_dts_in < PTS_HZ:
                                    self.v_frame = dts - prev_v_dts_in
                                prev_v_dts_in = dts
                                write_ts(buf, pts_at, pts + off90)
                                if dts_at >= 0:
                                    write_ts(buf, dts_at, dts + off90)
                                q = pts + off90
                                max_v_pts = q if max_v_pts is None else max(max_v_pts, q)
                                if chunk_off + o >= last_v_off and not v_done:
                                    # the file's final picture: send the rest of it and the
                                    # audio that belongs with it as a small burst, like a cut
                                    v_done = True
                                    tail_limit = self.bitrate // 8 * 2
                                    a_end = max_v_pts - off90 + self.v_frame
                    if v_pass:
                        out_pid = OUT_VIDEO_PID
                        res.video_pkts += 1
                elif pid == a_pid:
                    if pk.pusi:
                        pts, _, pts_at, _ = pes_timestamps(buf, pk.payload, o + TS)
                        if pts >= 0:
                            if a_end is not None and pts >= a_end:
                                a_done = True
                                a_pass = False
                            else:
                                a_pass = pts >= a_floor
                            if a_pass:
                                write_ts(buf, pts_at, pts + off90)
                                p = pts + off90
                                if max_a_pts is not None and 0 < p - max_a_pts < PTS_HZ // 5:
                                    self.a_frame = p - max_a_pts
                                max_a_pts = p if max_a_pts is None else max(max_a_pts, p)
                    if a_pass:
                        out_pid = OUT_AUDIO_PID
                        res.audio_pkts += 1
                elif pid == NULL_PID and not v_done:
                    out_pid = NULL_PID

                if out_pid is not None:
                    if pk.pcr_at >= 0:
                        if pid == pcr_pid and out_pid == OUT_VIDEO_PID:
                            v = read_pcr(buf, pk.pcr_at) + off27
                            if self.last_pcr_out is not None and v <= self.last_pcr_out:
                                v = self.last_pcr_out + 1
                            write_pcr(buf, pk.pcr_at, v)
                            self.last_pcr_out = v
                        else:
                            buf[pk.pcr_at - 1] &= ~0x10   # PCR only lives on the video PID
                            buf[pk.pcr_at:pk.pcr_at + 6] = b"\xFF" * 6
                    self._housekeeping()
                    self._forward(buf, o, pk, out_pid)
                else:
                    self._housekeeping()

                if v_done and (a_done or tail_bytes >= tail_limit):
                    break
                o += TS
            else:
                continue
            break

        if max_v_pts is not None:
            self.last_v_pts = max_v_pts
        if max_a_pts is not None:
            self.last_a_pts = max_a_pts
        res.ok = started and res.video_pkts > 0
        if seg_clock0 is not None:
            res.aired_s = (self.clock - seg_clock0) / CLK
        if not started:
            res.reason = "in-point beyond end of file" if in_s > 0 else "no keyframe found"

    def _forward(self, buf, o, pk, out_pid):
        if out_pid != NULL_PID:
            if pk.afc & 0x01:
                cc = (self.cc.get(out_pid, 15) + 1) & 0x0F
                self.cc[out_pid] = cc
            else:
                cc = self.cc.get(out_pid, 0)
            buf[o + 1] = (buf[o + 1] & 0xE0) | (out_pid >> 8)
            buf[o + 2] = out_pid & 0xFF
            buf[o + 3] = (buf[o + 3] & 0xF0) | cc
        self._emit(buf[o:o + TS])

    def _housekeeping(self):
        c = self.clock
        if c >= self.next_psi:
            self.next_psi = c + PSI_INTERVAL
            self._emit(_section_packet(0, self._next_cc(0), build_pat(self.tsid, self.program, OUT_PMT_PID)))
            streams = [(self.v_type or 0x02, OUT_VIDEO_PID, self.v_info)]
            if self.a_type is not None:
                streams.append((self.a_type, OUT_AUDIO_PID, self.a_info))
            self._emit(_section_packet(OUT_PMT_PID, self._next_cc(OUT_PMT_PID),
                                       build_pmt(self.program, OUT_VIDEO_PID, streams)))
        if c >= self.next_sdt:
            self.next_sdt = c + SDT_INTERVAL
            self._emit(_section_packet(SDT_PID, self._next_cc(SDT_PID),
                                       build_sdt(self.tsid, self.program, self.provider, self.service_name)))
        if self.last_pcr_out is None or c - self.last_pcr_out >= PCR_INTERVAL:
            v = c if self.last_pcr_out is None else max(c, self.last_pcr_out + 1)
            pkt = bytearray([0x47, OUT_VIDEO_PID >> 8, OUT_VIDEO_PID & 0xFF,
                             0x20 | self.cc.get(OUT_VIDEO_PID, 0), 183, 0x10]) + b"\x00" * 6 + b"\xFF" * 176
            write_pcr(pkt, 6, v)
            self.last_pcr_out = v
            self._emit(pkt)

    def _next_cc(self, pid):
        cc = (self.cc.get(pid, 15) + 1) & 0x0F
        self.cc[pid] = cc
        return cc

    def _emit(self, pkt):
        if self.dgram_n == 0:
            self.dgram_clock = self.clock
        self.dgram += pkt
        self.dgram_n += 1
        if self.dgram_n >= PKTS_PER_DGRAM:
            self._flush()

    def _flush(self):
        if self.dgram_n:
            self.pacer.wait_until(self.dgram_clock)
            self.sink.send(bytes(self.dgram), self.dgram_clock)
            self.dgram = bytearray()
            self.dgram_n = 0

    def _last_pid_offset(self, f, pid, size, window=TS * 20000):
        """Byte offset of the last PES start on `pid` (so EOF tails can be handled like cuts)."""
        start = max(0, size - window)
        start -= start % TS
        f.seek(start)
        data = f.read(size - start)
        for o in range(len(data) - len(data) % TS - TS, -1, -TS):
            if data[o] == 0x47 and data[o + 1] & 0x40 and (((data[o + 1] & 0x1F) << 8) | data[o + 2]) == pid:
                return start + o
        return size

    def _first_video_pts(self, f, v_pid, pos, limit=TS * 20000):
        f.seek(pos - pos % TS)
        data = bytearray(f.read(limit))
        for o in range(0, len(data) - TS + 1, TS):
            if data[o] != 0x47:
                continue
            pk = Pkt(data, o)
            if pk.pid == v_pid and pk.pusi:
                pts, _, _, _ = pes_timestamps(data, pk.payload, o + TS)
                if pts >= 0:
                    return pts
        return None

    def _estimate_bitrate(self, f, pcr_pid):
        f.seek(0)
        data = bytearray(f.read(TS * 4000))
        pcrs = []
        for o in range(0, len(data) - TS + 1, TS):
            if data[o] == 0x47:
                pk = Pkt(data, o)
                if pk.pid == pcr_pid and pk.pcr_at >= 0:
                    pcrs.append((o, read_pcr(data, pk.pcr_at)))
        if len(pcrs) >= 2 and pcrs[-1][1] > pcrs[0][1]:
            br = (pcrs[-1][0] - pcrs[0][0]) * 8 * CLK // (pcrs[-1][1] - pcrs[0][1])
            if 500_000 < br < 40_000_000:
                self.bitrate = br

    def _seek(self, f, v_pid, target_pts, size):
        """Binary search for a byte offset whose next video PTS is just before target."""
        lo, hi = 0, size // TS
        best = 0
        for _ in range(40):
            if hi - lo < 64:
                break
            mid = (lo + hi) // 2
            pts = self._first_video_pts(f, v_pid, mid * TS, limit=TS * 4000)
            if pts is None or pts > target_pts:
                hi = mid
            else:
                best = mid
                lo = mid
        return best * TS
