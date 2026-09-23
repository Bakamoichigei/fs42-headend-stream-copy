"""Stream-copy splicer tests. Needs ffmpeg/ffprobe on PATH (skipped otherwise)."""
import os
import shutil
import subprocess
import tempfile
import unittest
from collections import Counter

from fs42.headend.ts_splicer import (TSChannelOutput, Pkt, read_pcr, pes_timestamps,
                                     crc32_mpeg, TS)

HAVE_FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
PREP = os.path.join(os.path.dirname(__file__), "..", "tools", "headend_prep.sh")


def _clip(path, seconds, freq):
    src = path + ".src.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30000/1001",
                    "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000", "-t", str(seconds),
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", src], check=True)
    subprocess.run(["bash", PREP, src, path], check=True, capture_output=True,
                   env=dict(os.environ, LOUDNORM="0"))


def _analyse(path):
    data = bytearray(open(path, "rb").read())
    cc, cc_err, pcr_last, pcr_back, crc_bad = {}, 0, None, 0, 0
    vpts, apts = [], []
    for o in range(0, len(data), TS):
        pk = Pkt(data, o)
        if pk.pid != 0x1FFF and pk.afc & 1:
            c = data[o + 3] & 15
            if pk.pid in cc and c != (cc[pk.pid] + 1) & 15:
                cc_err += 1
            cc[pk.pid] = c
        if pk.pcr_at >= 0:
            v = read_pcr(data, pk.pcr_at)
            if pcr_last is not None and v <= pcr_last:
                pcr_back += 1
            pcr_last = v
        if pk.pusi and pk.pid in (0x100, 0x101):
            pts = pes_timestamps(data, pk.payload, o + TS)[0]
            (vpts if pk.pid == 0x100 else apts).append(pts)
        if pk.pusi and pk.pid in (0, 0x11, 0x1000):
            p = pk.payload + 1
            ln = ((data[p + 1] & 15) << 8) | data[p + 2]
            crc_bad += crc32_mpeg(data[p:p + 3 + ln]) != 0
    vs = sorted(vpts)
    return dict(cc_err=cc_err, pcr_back=pcr_back, crc_bad=crc_bad,
                vsteps=Counter(b - a for a, b in zip(vs, vs[1:])),
                a_back=sum(1 for a, b in zip(apts, apts[1:]) if b <= a))


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
class TestSplicer(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.a = os.path.join(cls.tmp, "a.ts")
        cls.b = os.path.join(cls.tmp, "b.ts")
        _clip(cls.a, 12, 440)
        _clip(cls.b, 9, 880)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_seamless_splices(self):
        out = os.path.join(self.tmp, "out.ts")
        o = TSChannelOutput(f"file://{out}", "TEST", realtime=False)
        results = [o.splice(self.a, 0, 5.0),      # cut
                   o.splice(self.b, 2.4, 3.0),    # in-point + cut
                   o.splice(self.a, 7.0, None),   # to EOF
                   o.splice(self.b, 0, None)]     # whole file
        o.close()
        for r in results:
            self.assertTrue(r.ok, r)
        self.assertLess(abs(results[1].start_error_s), 0.6)

        s = _analyse(out)
        self.assertEqual(s["cc_err"], 0)
        self.assertEqual(s["pcr_back"], 0)
        self.assertEqual(s["crc_bad"], 0)
        self.assertEqual(s["a_back"], 0)
        # display timeline is continuous: every step is one frame (allow ~2 frames of slack)
        irregular = {k: v for k, v in s["vsteps"].items() if k != 3003}
        self.assertTrue(all(0 < k <= 3003 * 3 for k in irregular), irregular)

        dec = subprocess.run(["ffmpeg", "-v", "warning", "-i", out, "-f", "null", "-"],
                             capture_output=True, text=True)
        self.assertEqual(dec.stderr.strip(), "")

    def test_past_eof_and_missing(self):
        o = TSChannelOutput(f"file://{os.path.join(self.tmp, 'x.ts')}", "TEST", realtime=False)
        self.assertFalse(o.splice(self.a, 999, 5).ok)
        self.assertFalse(o.splice(os.path.join(self.tmp, "nope.ts"), 0, 5).ok)
        self.assertAlmostEqual(o.gap(1.0), 1.0)
        o.close()


if __name__ == "__main__":
    unittest.main()
