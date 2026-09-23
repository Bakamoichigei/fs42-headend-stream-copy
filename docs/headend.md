# FS42 Headend: every channel at once, stream copy

`headend.py` plays every scheduled FS42 station at the same time. Each one
goes out as its own MPEG-2 transport stream over UDP multicast, and nothing
is decoded or re-encoded. The intended use is feeding a bank of IP set-top
decoders, one per channel (for example the VBrick XTV125D). Each decoder's
composite output then feeds an RF modulator on the CATV plant.

```
 transcode box                 FS42 host (headend.py)                      closet rack
 ─────────────                 ──────────────────────                      ───────────
 headend_prep.sh ──► NAS ──►   ch 3 worker ─► 239.42.0.3:5000 ─┐
   (house format)              ch 4 worker ─► 239.42.0.4:5000 ─┤ IGMP-     XTV125D ─► composite ─► modulator ─┐
                               ...                             ├ snooping  XTV125D ─► composite ─► modulator ─┼─► combiner ─► coax
                               ch14 worker ─► 239.42.0.14:5000─┘ switch    ...                                ┘
```

The splicer is pure Python (standard library only). It reads TS packets from
disk and forwards them, rewriting only transport-layer fields:

* **PTS/DTS/PCR** are shifted, so every channel's timeline runs on without a break from file to file.
* **PIDs** are remapped to one fixed layout: PMT 0x1000, video 0x100 (which also carries PCR), audio 0x101.
* **Continuity counters** are regenerated.
* **PAT/PMT** are regenerated every 100 ms and the **SDT** every 1 s. The SDT's service name is the FS42 `network_name`.

Packets leave at the rate the rewritten PCR implies, so output is constant
bit rate and paced like a hardware mux. One channel uses about 4% of one CPU core.

### How it stays on schedule

Before each item, the worker asks the FS42 schedule what should be on air at
the moment the next packet will display. It then splices that file in at the
right in-point. Each lookup re-anchors to the schedule, so rounding errors
never build up.

### Splice quality (measured on a 15-minute, 3-channel render, about 100 splices per channel)

* **Video:** the displayed frames stay continuous across cuts. Cuts land just before an I or P picture, so display order is never broken.
* **Audio:** each cut loses at most about two MP2 frames, roughly 20–50 ms.
* **In-points** snap to a GOP start, which is within 0.5 s of the requested point with the house GOP of 15 frames.
* **Transport:** 0 continuity errors, 0 PCR discontinuities, and a PCR interval of 40 ms or less. `ffmpeg` decodes the output with no warnings.

## 1. Prepare the media (on the transcode machine)

Every file that airs on a channel must share identical codec parameters.
That is the price of stream copy. Use `tools/headend_prep.sh`:

```bash
tools/headend_prep.sh movie.mkv /nas/fs42/catalog/kmov/movie/movie.ts
JOBS=4 tools/headend_prep.sh --dir /nas/incoming /nas/fs42/catalog   # mirror a whole tree
tools/headend_prep.sh --slate runtime/slate.ts                        # bars & tone filler
```

House format:

| | |
|---|---|
| Container | MPEG-TS, 188-byte packets, CBR `muxrate` 7 Mb/s, PCR every 20 ms, one audio frame per PES |
| Video | MPEG-2 MP@ML 720×480, 29.97 interlaced TFF, SAR 8:9 (4:3), **closed GOP** N=15 M=3, 4.5 Mb/s average (6 Mb/s peak) |
| Audio | MPEG-1 Layer II, 48 kHz stereo, 192 kb/s, loudness normalised to −24 LUFS |

Build the FS42 catalogs from the prepared `.ts` files, which FS42 already
accepts. The other option is to keep cataloguing your originals and map
the paths with `path_rewrite` (see below). In that case the prepared twin
must have the same duration as the original.

## 2. Configure

Add a `headend` block to `confs/main_config.json`. Every key is optional:

```json
"headend": {
  "multicast_base": "239.42.0.0",
  "port": 5000,
  "ttl": 4,
  "interface": "192.168.10.2",
  "encapsulation": "udp",
  "slate_file": "runtime/slate.ts",
  "schedule_lead_s": 0.7,
  "auto_extend_schedule": true,
  "exclude": [99],
  "channels": { "3": {"group": "239.42.1.3", "port": 1234},
                "4": {"url": "rtp://239.42.0.4:5004?ttl=2"} },
  "path_rewrite": [ {"from": "/media/originals/", "to": "/media/house/", "ext": ".ts"} ]
}
```

* **`multicast_base`**: channel *N* goes to `base + N`, so channel 3 is `239.42.0.3`.
* **`interface`**: the IP of the NIC that faces the decoders. Set it whenever the host has more than one NIC.
* **`encapsulation`**: `udp` sends raw TS with 7 packets per datagram. `rtp` adds RTP headers (payload type 33).
* **`schedule_lead_s`**: adds decoder latency to each schedule lookup, so what appears on screen lines up with the wall clock.
* **`auto_extend_schedule`**: when a channel runs off the end of its schedule, it extends that schedule by a day. The extension runs under a lock shared by all workers. Keep your usual nightly `station_42.py` run anyway.
* **Skipped channels:** guide, web, streaming and executable channels can't be stream-copied. They are skipped with a warning.

## 3. Run

```bash
python3 headend.py --list              # channel -> multicast group table
python3 headend.py --check             # probe every file due in the next 24 h against the slate's format
python3 headend.py                     # go (Ctrl-C / SIGTERM for a clean stop)
python3 headend.py -c 3,4              # a subset
python3 headend.py --record /tmp/rec --duration 600 --fast   # render channels to files, faster than realtime
```

`install/systemd/fs42-headend.service.template` runs the headend as a
service. Each channel writes its status to `runtime/headend/chNN.json`.
The file shows what's playing now, splice and error counts, and output
stalls (NAS hiccups).

`headend.py` doesn't use mpv. You can run it alongside `field_player.py`,
since both read the same schedule database.

**If something goes wrong on a channel:**

* **Missing file, unreadable file or unscheduled gap:** the slate is shown for that stretch.
* **No slate file:** the mux stays up and sends only PSI, PCR and null packets. The decoder holds its last frame.
* **Worker crash:** the supervisor restarts the worker with backoff.

## 4. Network

At 12 × 7 Mb/s, the headend sends about 85 Mb/s of multicast.

* **IGMP snooping:** without it, a switch floods that traffic to every port, including Wi-Fi APs. Use a switch with snooping on and an IGMP querier. A dedicated VLAN or switch for the decoders is better still.
* **`ttl`:** keep it small.
* **Wired only:** keep all of this off Wi-Fi.

## 5. VBrick XTV125D notes

The XTV125D (part no. 8000-0188) is an IP set-top decoder with composite,
component and HDMI outputs. Among its supported stream types is
"MPEG2 Multicast Live", which is what this headend emits.

* **One box per channel:** each box stays on its channel's multicast group.
* **Standalone use:** the boxes run in "Local Mode" from a `channels.xml` in `/root/data/`, with no VEMS server needed. The quick-start guide gives the defaults: telnet `iptv`/`settopbox`, setup password `1234`.
* **Video output:** set the output to **480i**, since the factory default is 720p. The composite output then carries native NTSC.
* **`channels.xml` syntax:** check the exact entry for a multicast channel against the "Sample Channels File" section of the quick-start manual. It hasn't been verified here.
