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
| `tools/prevue/prevue.fs-uae` | FS-UAE settings matching the community's WinUAE setup. | **Not yet tested** with the real software |

## What you need to supply

1. **Kickstart 2.04 ROM (rev 37.175).** It's still under copyright, and the legitimate source is Cloanto's
   *Amiga Forever*. The free AROS replacement ROM does **not** run Prevue.
2. **The Prevue software.** Version 9.0.4 is preserved at
   [archive.org/details/prevue](https://archive.org/details/prevue). Version 7.8.3 exists too but
   needs manual patching; see the [emulation guides](https://prevueguide.neocities.org/guides/Esquire).
3. **Packages on the FS42 host:** `apt install fs-uae xvfb ffmpeg`.
4. **Optional:**
   - a music folder for the audio bed;
   - a promo video to show through the "genlock" (the real channel's top half was satellite video
     behind the Amiga's graphics).

## Emulated machine

The emulator is set up to match the community WinUAE configuration:

- **CPU and chipset:** 68000, Full ECS, **NTSC**.
- **Memory:** 1 MB chip RAM plus 8 MB Zorro II fast RAM.
- **Boot disk:** `PREVUE.ADF` in DF0 with turbo floppy speed, or the extracted software folder as a hard drive.

When the Amiga boots with no data yet, it shows **ER007**. That clears once the first listings arrive.

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
  shouldn't shift anything. **Verify this against the emulator**, and adjust if the grid's times
  come out an hour or more off.

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
- the timezone/DST handling described above;
- which colour the genlock should key (`PREVUE_KEY_COLOR`), which means finding the palette colour
  the software leaves "transparent";
- whether 9.0.4 does the `scroll` list format, or whether 7.8.3 is needed for it;
- how much of 9.0.4's TV Guide Channel branding the custom logo/ad files can turn back into Prevue.

Credits: the protocol work is Ari Weinstein's
[PrevueCLI](https://github.com/AriX/PrevueCLI) (BSD) and the prevueguide.com community.
