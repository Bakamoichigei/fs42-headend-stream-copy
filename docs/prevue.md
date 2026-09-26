# Prevue channel: the real Prevue Guide software, fed by FS42

This runs the actual Amiga Prevue Guide software in an emulator. It shows
your FS42 channels and whatever they're scheduled to air, and it goes out on
the headend as a channel of its own.

```
FS42 schedules ─► prevue_feed.py ─TCP─► prevue_serial_bridge.py ─pty─► FS-UAE (Amiga + Prevue ESQ)
                  (UVSG satellite                                           │ virtual display (Xvfb)
                   data protocol)                                           ▼
                                               ffmpeg: grab ─ [genlock key over promo video] ─ + music
                                                         └─► house-format MPEG-2 TS ─► multicast channel
```

| Piece | What it does | Status |
|---|---|---|
| `fs42/prevue/protocol.py` | Speaks the UVSG data protocol in pure Python. It's a port of [PrevueCLI](https://github.com/AriX/PrevueCLI)'s encoders. | Byte-exact against every PrevueCLI test fixture (`test/test_prevue_protocol.py`) |
| `fs42/prevue/listings.py` | Turns FS42 schedule blocks into Prevue's channels and half-hour timeslot programs. | Tested against a live FS42 schedule |
| `prevue_feed.py` | Sends config, clock, DST, title, text ads and two days of listings, paced like a 2400-baud line. Refreshes every 30 minutes and does a full reload each 5 AM listings day. | Tested through the bridge |
| `tools/prevue_serial_bridge.py` | A virtual serial cable (pseudo-terminal ↔ TCP) that survives feeder restarts. | Tested |
| `tools/prevue/prevue_channel.sh` | Runs everything above plus the capture and encode, for one headend channel. | Capture, genlock key, music and encode tested with a stand-in emulator |
| `tools/prevue/prevue-winuae.uae` | The WinUAE configuration verified to run Prevue 9.0.4. | **Working** |
| `tools/prevue/prevue.fs-uae` | FS-UAE settings mirroring that WinUAE setup. | **Not yet tested** |

For rebranding (logos, promo cards, banner) and keyboard commands, see
[prevue-customizing.md](prevue-customizing.md).

## What you need to supply

1. **Kickstart ROMs from Cloanto's *Amiga Forever*.** They're still under copyright, so that's the
   legitimate source. The working setup uses Kickstart 2.04 (rev 37.175, the A500+ ROM). The free
   AROS replacement ROM does **not** run Prevue.
2. **The Prevue software.** Version 9.0.4 is preserved at
   [archive.org/details/prevue](https://archive.org/details/prevue). Version 7.8.3 exists too but
   needs manual patching; see the [emulation guides](https://prevueguide.neocities.org/guides/Esquire).
3. **Packages on the FS42 host:** `apt install fs-uae xvfb ffmpeg`.
4. **Optional:**
   - a music folder for the audio bed;
   - a promo video to show through the "genlock" (the real channel's top half was satellite video
     behind the Amiga's graphics).

## Emulated machine (verified in WinUAE, 2026-09-23)

The working configuration is saved as **`tools/prevue/prevue-winuae.uae`**. Load it in WinUAE
and point its ROM and floppy paths at your files. The settings that matter:

| Setting | Value |
|---|---|
| Compatibility preset | **A500+** (`chipset_compatible=A500+`, `rtc=MSM6242B`) |
| CPU | 68000, cycle-exact |
| Chipset | **Full ECS**, **NTSC** |
| Kickstart | 2.04 rev 37.175 (A500+) |
| Memory | 1 MB chip, 8 MB Zorro II fast, **no slow RAM** |
| Genlock | **on** (`genlock=true`, `genlock_alpha=true`) |
| Floppy | `PREVUE.ADF` in DF0, turbo speed |
| Serial | `TCP://0.0.0.0:1234` |

It boots to the clock, the timeslots and **ER007**. `prevue_feed.py --demo --port 1234`
then fills the grid (channel highlight and movie colours included) and sets the clock.
With full cycle-exact emulation, it keeps real time on a modern PC.

Lessons learned:

- **Genlock is required.** The software expects to be keying over satellite video.
  Without a genlock "connected", it goes black and stalls after the boot CLI.
  WinUAE's genlock source defaults to nothing (black), and it can also be noise, a test card, a PNG,
  **a video file, or a capture device**. So WinUAE can do the "satellite video" itself,
  keyed by the Amiga's real transparency. That's more faithful than keying a colour
  afterwards in ffmpeg (`PREVUE_KEY_COLOR`), which becomes a fallback for emulators without
  those genlock sources.
- **No slow RAM.** The earlier A500+ attempt that hung at "System Initializing" had 512 KB of
  slow ("trapdoor") RAM from the preset. The working config has `bogomem_size=0`. That's the
  most likely difference.
- **Skip the A3000 preset.** It needs a 68030, emulating it costs far more CPU, and the
  Prevue clock fell behind.
- **Clock:** the box displayed the time about 2 s late. The feeder now stamps the clock
  as it's sent, sends it first and last, and runs it `clock_advance_s` (default 2) ahead.
- **Time zone:** the default `timezone: 6`, with the feeder sending local wall-clock
  time, put every show in the right slot.

FS-UAE (for the Linux host) still needs the same genlock setting. It's passed through
as a raw UAE option (`uae_genlock`); if this FS-UAE build doesn't honour it, the fallback
is WinUAE under Wine.

## Configure

Add this block to `confs/main_config.json` for the feeder:

```json
"prevue": {
  "software": "9",
  "display_format": "grid",
  "title": "BAKACAST CABLE",
  "scroll_speed": 3,
  "timezone": 6,
  "ads": [ [["BEFORE YOU VIEW,", "center"], ["PREVUE!", "center"]] ],
  "channels": { "4":  {"call_letters": "KMOV", "movies": true},
                "3":  {"hilite": true},
                "40": {"call_letters": "WEATHER", "title": "Local Forecast"},
                "42": {"title": "Prevue Guide"} },
  "exclude": []
}
```

- **`display_format`:** `grid`, or `scroll` for the list format. PrevueCLI notes that 7.8.3 has both;
  whether 9.0.4 honours `scroll` still needs testing.
- **`channels.*.movies`:** marks everything on that channel as a movie. Separately, any block
  90 minutes or longer gets the movie attribute; set `movie_minutes` to change that threshold.
- **`channels.*.hilite` / `alt_hilite`:** the red or light-blue channel highlight in the grid.
- **Live channels in the grid:** the headend's `live_channels` (Prevue itself, the weather
  channel) are listed automatically, with one all-day program. `channels.*.title` names that
  program (the default is the live channel's `name`). A live channel replaces any FS42 station
  with the same number in the grid, as it does on the headend. To leave one out of the grid,
  put its number in `exclude`.
- **`timezone`:** the box's offset setting (hours west of GMT). The feeder sends clock and listings
  in the FS42 host's local wall-clock time. With `6` (Central, Prevue's home in Tulsa), the box
  doesn't shift anything. This is verified: shows landed in the right slots.
- **`clock_advance_s`:** how far ahead to send the clock (default 2 s) to cover the box's lag.

Then add the channel to the headend's `live_channels`:

```json
"headend": {
  "live_channels": {
    "42": { "name": "PREVUE",
           "command": "tools/prevue/prevue_channel.sh",
           "env": { "PREVUE_KICKSTART": "/opt/prevue/kick204.rom",
                    "PREVUE_DISK": "/opt/prevue/PREVUE.ADF",
                    "PREVUE_MUSIC": "/nas/music/prevue",
                    "PREVUE_PROMO": "/nas/fs42/promos/promo_loop.ts",
                    "PREVUE_KEY_COLOR": "0x000000" } }
  }
}
```

The headend gives the script its multicast destination and restarts it if anything in the chain
dies. `headend.py --list` shows it as a live channel.

## Hand-written listings (no FS42 needed)

To show off a full lineup before FS42 has real schedules, or on the Windows PC with WinUAE,
write the listings yourself in a JSON file and run:

```bash
python prevue_feed.py --listings mylineup.json --print                  # check it
python prevue_feed.py --listings mylineup.json --port 1234              # feed WinUAE and keep refreshing
```

Start from `confs/examples/prevue_listings.json`, which is a full 14-channel sample. The shape:

```json
{ "channels": [
    { "number": 2, "call": "WBAK", "hilite": true,
      "schedule": { "06:00": "Good Morning", "18:30": "Wheel of Fortune",
                    "20:00": {"title": "Prime Time Movie", "movie": true} },
      "saturday": { "07:00": "Saturday Cartoons", "12:00": {"title": "College Football", "sports": true} } },
    { "number": 4, "call": "BMOV", "movies": true,
      "loop": [[120, "Back to the Future"], [115, "The Goonies"]] }
] }
```

**Per channel:**

| Key | What it does |
|---|---|
| `number` | The channel number shown in the grid, e.g. `2` or `42`. The grid sorts by it. |
| `call` | Call letters or channel name. **7 characters at most**; longer is cut. |
| `source` | Optional internal ID, 6 characters at most. It's made from `call` if you leave it out. |
| `hilite` / `alt_hilite` | `true` gives the channel the red or light-blue highlight. |
| `ppv` / `stereo` / `no_video_tag` | Other channel attributes from the protocol. What 9.0.4 draws for each is still to map (see below). |
| `movies` | `true` shows everything on the channel in the movie colour. |
| `schedule` | `{"HH:MM": title, ...}` in 24-hour local time, used every day. Each show runs until the next start time. |
| `monday` … `sunday` | Same shape. Replaces `schedule` on that day. |
| `loop` | `[[minutes, title], ...]`, repeated from 5 AM. Use this instead of `schedule` for simple channels. |

**A title** is either plain text or `{"title": "...", "movie": true}`. The other program
attributes are `sports`, `alt_hilite`, `tag` and `repeat`.

**Mapping the colours:** the protocol has more attribute bits than the red and light-blue channel
highlights and the movie colour, and which colours 9.0.4 draws for the rest (a green, for instance)
hasn't been mapped yet. `confs/examples/prevue_flag_test.json` puts one attribute on each channel
from 2 to 13. Feed it with `--once`, look at the grid, and note what each one does here. The grid's
colours themselves come from `gradient.ini` on the disk (the `p` key reloads it), so a colour can
also be changed there.

**Things to know:**
- **Days run from 5 AM to 5 AM,** the way Prevue (and TV) counts them. `"saturday": {"01:00": "Late Movie"}`
  means late Saturday night, not early Saturday morning.
- **The grid works in half-hour slots.** A slot shows whatever is on at its :00 or :30. A show that
  starts at 7:15 appears from 7:30, and anything shorter than half an hour that doesn't cross a slot
  boundary won't appear at all. Real listings rounded the same way.
- **Keep titles short.** A half-hour cell only fits roughly 15–20 characters. Longer shows get wider
  cells, but abbreviating like the real guide did ("Wheel of Fortune" rather than
  "Wheel of Fortune with Pat Sajak & Vanna White") looks right. Stick to plain letters, digits and
  punctuation.
- **Two days of listings are sent,** and the file is re-read at every half-hour refresh, so edits show
  up at the next refresh. To send immediately, run it again with `--once`.
- **Channel settings:** `--listings` uses the feeder's built-in settings (title "BAKACAST CABLE",
  `timezone: 6` and so on) plus any command-line options, not `main_config.json`.

## Dot crawl on composite

Computer-drawn text has razor-sharp colour edges, and on a composite or RF TV each one
crawls with dots. `prevue_channel.sh` softens only the colour detail, horizontally, down to roughly
what NTSC can carry (about 1.3 MHz). It also trims saturation slightly. Brightness stays
sharp, so the text stays crisp. The code is in `tools/crt_soften.sh`, and it's on by default.

| Setting | Default | What it does |
|---|---|---|
| `CRT_CHROMA_SIGMA` | `1.4` | Horizontal colour blur, in pixels at 720 wide. Raise it (e.g. `2`) for more softening; `0` turns it off |
| `CRT_SATURATION` | `0.9` | Saturation multiplier. `1` leaves colour saturation unchanged |

Put them in the channel's `env` block to compare on a real set.

## Useful commands

```bash
python3 prevue_feed.py --print                 # the lineup + listings FS42 would send
python3 prevue_feed.py --listings my.json --print   # a hand-written lineup instead (see above)
python3 prevue_feed.py --dump feed.bin         # the raw byte stream, for inspection
tools/prevue_serial_bridge.py &                # then point FS-UAE (or WinUAE on another PC) at it
python3 prevue_feed.py --once                  # push one full update
```

The feeder also talks to WinUAE directly. Set WinUAE's serial port to `TCP://0.0.0.0:5541`, then
run `prevue_feed.py --host <that PC> --once`. That's the fastest way to try the software on a
Windows machine before setting up the Linux host.

## Still to verify with the real software

- whether FS-UAE accepts the bridge's pseudo-terminal as `serial_port` (WinUAE's TCP serial is the
  documented route);
- what happens at a DST change (the boundaries are sent, but no switch-over has been watched yet);
- whether FS-UAE honours `uae_genlock` (required: see above);
- the genlock source: a WinUAE video file or capture device (preferred) versus ffmpeg keying
  (`PREVUE_KEY_COLOR`), and whether FS-UAE has comparable genlock sources, or whether the Linux host
  should run WinUAE under Wine;
- whether 9.0.4 does the `scroll` list format, or whether 7.8.3 is needed for it;
- how much of 9.0.4's TV Guide Channel branding the custom logo/ad files can turn back into Prevue.

Credits: the protocol work is Ari Weinstein's
[PrevueCLI](https://github.com/AriX/PrevueCLI) (BSD) and the prevueguide.com community.
