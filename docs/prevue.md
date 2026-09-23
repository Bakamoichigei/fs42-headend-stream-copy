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
  "channels": { "4": {"call_letters": "KMOV", "movies": true},
                "3": {"hilite": true} },
  "exclude": [2]
}
```

- **`display_format`:** `grid`, or `scroll` for the list format. PrevueCLI notes that 7.8.3 has both;
  whether 9.0.4 honours `scroll` still needs testing.
- **`channels.*.movies`:** marks everything on that channel as a movie. Separately, any block
  90 minutes or longer gets the movie attribute; set `movie_minutes` to change that threshold.
- **`channels.*.hilite` / `alt_hilite`:** the red or light-blue channel highlight in the grid.
- **`timezone`:** the box's offset setting (hours west of GMT). The feeder sends clock and listings
  in the FS42 host's local wall-clock time. With `6` (Central, Prevue's home in Tulsa), the box
  doesn't shift anything. This is verified: shows landed in the right slots.
- **`clock_advance_s`:** how far ahead to send the clock (default 2 s) to cover the box's lag.

Then add the channel to the headend's `live_channels`:

```json
"headend": {
  "live_channels": {
    "2": { "name": "PREVUE",
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

## Useful commands

```bash
python3 prevue_feed.py --print                 # the lineup + listings FS42 would send
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
