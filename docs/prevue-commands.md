# Prevue feeder: quick reference

All the commands for `prevue_feed.py`, which sends listings, the clock and settings to the Prevue
Guide software over its (emulated) serial port. For setup and background, see [prevue.md](prevue.md).

**Run these from the repo folder.**

| | Windows | Linux (the A10) |
|---|---|---|
| Go to the repo | `cd /d X:\GitHub\fs42-headend-stream-copy` | `cd ~/fs42 && source env/bin/activate` |
| Python command | `py` | `python3` |

The examples below use `py` and Windows paths. On Linux, swap in `python3` and forward slashes.

## Before you send anything

- **WinUAE is running** with `tools/prevue/prevue-winuae.uae` loaded. It listens on **TCP port 1234**.
- Prevue has booted to the clock and timeslots (showing **ER007**, "no data", which is normal before the first feed).
- The feeder waits and retries until it can connect, so starting it before WinUAE is fine.

## The everyday commands

| What | Command |
|---|---|
| **Demo lineup** (built in, 5 channels), once | `py prevue_feed.py --demo --port 1234 --once` |
| **Your own listings**, once | `py prevue_feed.py --listings mylineup.json --port 1234 --once` |
| **Your own listings**, and keep refreshing every 30 min (leave it running) | `py prevue_feed.py --listings mylineup.json --port 1234` |
| **The 14-channel sample lineup** | `py prevue_feed.py --listings confs\examples\prevue_listings.json --port 1234 --once` |
| **The colour/flag test** (one attribute per channel, 2–13) | `py prevue_feed.py --listings confs\examples\prevue_flag_test.json --port 1234 --once` |
| **Real FS42 schedules** (on the A10, once FS42 has schedules) | `python3 prevue_feed.py --once`, or leave off `--once` to keep refreshing |

Stop a running feeder with **Ctrl-C**.

A full send of 14 channels takes about **1½ minutes**, because it's paced like a real 2400-baud line.
The grid fills in as the data arrives.

## Checking without sending

| What | Command |
|---|---|
| Check a listings file and show what would be sent | `py prevue_feed.py --listings mylineup.json --print` |
| The same for the demo | `py prevue_feed.py --demo --print` |
| Write the raw serial bytes to a file instead | `py prevue_feed.py --listings mylineup.json --dump feed.bin` |

`--print` catches mistakes in a listings file with a plain message, such as
*"start time '7pm' should look like 19:30"*, before anything goes to the emulator.

## All the options

| Option | What it does |
|---|---|
| `--demo` | Send the built-in 5-channel demo lineup. |
| `--listings FILE` | Send a hand-written JSON lineup. The format is in [prevue.md → Hand-written listings](prevue.md#hand-written-listings-no-fs42-needed). |
| *(neither)* | Use FS42's real schedules. This needs an FS42 install, so the A10. |
| `--port N` | The emulator's serial port. WinUAE's config uses `1234`. Without it, the feeder uses the config's port (`5541`, the Linux serial bridge). |
| `--host NAME` | The machine running the emulator (default `127.0.0.1`, this PC). For example, `--host shogoki` feeds WinUAE on the desktop from another machine. |
| `--once` | Send one full update and exit. Without it, the feeder keeps running and refreshes every 30 minutes. |
| `--print` | Show the lineup and every program record, and send nothing. |
| `--dump FILE` | Write the byte stream to a file instead of sending it. |
| `--format grid` / `--format scroll` | Grid or scrolling-list layout. `scroll` probably needs 7.8.3; 9.0.4 is expected to ignore it. |
| `--software 9` / `--software 7.8.3` | Which Prevue version you're feeding (default `9`). |

**Which settings apply:** with `--demo` or `--listings`, the feeder uses its built-in settings
(title *BAKACAST CABLE*, `timezone: 6`, the "BEFORE YOU VIEW, PREVUE!" text ad) plus the options
above. With FS42's schedules, it uses the `prevue` block in `confs/main_config.json`.

## Listings file cheat sheet

```json
{ "channels": [
  { "number": 2, "call": "WBAK", "hilite": true,
    "schedule": { "06:00": "Good Morning", "18:30": "Wheel of Fortune",
                  "20:00": {"title": "Prime Time Movie", "movie": true} },
    "saturday": { "07:00": "Saturday Cartoons" } },
  { "number": 4, "call": "BMOV", "movies": true,
    "loop": [[120, "Back to the Future"], [115, "The Goonies"]] }
] }
```

- **Channel keys:**
  - `number` and `call` are required; `call` is 7 characters at most;
  - optional: `hilite` (red), `alt_hilite` (light blue), `movies` (the whole channel in the movie colour);
  - also accepted: `ppv`, `stereo`, `no_video_tag`.
- **Shows:** either `schedule` (24-hour start times, every day), with optional `monday` … `sunday`
  overrides, or `loop` (`[minutes, title]` pairs, repeated from 5 AM).
- **A title** is plain text or `{"title": "...", "movie": true}`. Other title flags are `sports`,
  `alt_hilite`, `tag` and `repeat`.
- **Days run from 5 AM to 5 AM.** The grid snaps to half hours. Keep titles to about 15–20 characters.
- **Edits** show up at the next half-hour refresh, or right away if you run it again with `--once`.

## On the A10 (Linux, with FS-UAE)

The emulator's serial port is a virtual one there, so a small bridge sits in between:

```bash
tools/prevue_serial_bridge.py --link /tmp/prevue-serial --port 5541 &   # start before FS-UAE
python3 prevue_feed.py                                                   # feeds the bridge on 5541
```

In production you don't run these by hand: `tools/prevue/prevue_channel.sh` starts the bridge,
the emulator, the feeder and the encoder together, and the headend starts that script for channel 42.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| The feeder sits at "connecting" | WinUAE isn't running, its serial port isn't `TCP://0.0.0.0:1234`, or the firewall is blocking WinUAE. Allow it when Windows asks, or add it by hand. |
| `python` opens the Microsoft Store | Use `py`, or turn off the "python" entries in Settings → Apps → Advanced app settings → App execution aliases. |
| The grid stays empty after a send | Give it the full 1–2 minutes. Check the clock on screen is right: listings for the wrong day don't show. |
| Shows land an hour off | `timezone` (default `6`) and the PC's clock or DST settings disagree. See [prevue.md](prevue.md). |
| The screen goes black after boot | Genlock is off in WinUAE. It must be on. |
