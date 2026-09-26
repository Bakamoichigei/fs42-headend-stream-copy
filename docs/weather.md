# Weather channel: WeatherStar 4000+ as a live headend channel

This runs [WeatherStar 4000+](https://github.com/netbymatt/ws4kp) (ws4kp), a faithful
recreation of The Weather Channel's early-'90s local forecast, and sends it out on the
headend as a channel of its own, with a smooth-jazz music bed.

```
ws4kp (local Node server, NWS data) ─► Chromium, kiosk mode, 640×480 on a virtual display (Xvfb)
                                            │
                     ffmpeg: grab ──────────┴─ + shuffled music folder
                               └─► house-format MPEG-2 TS (720×480i, 4:3, 7 Mb/s) ─► multicast channel
```

| Piece | What it does | Status |
|---|---|---|
| `tools/weather/weather_channel.sh` | Starts ws4kp, the virtual display, Chromium and the encoder for one headend channel. Relaunches the browser if it dies, and once a day to shed memory. | Capture, encode, music, browser relaunch and error handling tested in the sandbox |
| ws4kp v7.1.6 | The WeatherStar pages themselves, served locally. | Page renders full-frame at 640×480 in kiosk mode. **Live NWS data not yet seen** (the sandbox can't reach weather.gov) |

The forecast data comes from the US National Weather Service, so the location must be in the US.

## Install (on the headend box)

```bash
sudo apt install chromium xvfb ffmpeg nodejs npm git curl
sudo git clone --branch v7.1.6 --depth 1 https://github.com/netbymatt/ws4kp /opt/ws4kp
sudo chown -R "$USER" /opt/ws4kp
cd /opt/ws4kp && npm ci --omit=dev
```

`--branch v7.1.6` pins the version, so an upstream change can't alter the channel
under you. To upgrade later: `cd /opt/ws4kp && git fetch --tags && git checkout <new tag> && npm ci --omit=dev`.

## Configure

Add the channel to the headend's `live_channels` in `confs/main_config.json`:

```json
"headend": {
  "live_channels": {
    "40": { "name": "WEATHER",
           "command": "bash tools/weather/weather_channel.sh",
           "env": { "WEATHER_LOCATION": "05443, USA",
                    "WEATHER_MUSIC": "/nas/music/weatherstar" } }
  }
}
```

Channel 40 (for the WeatherStar 4000) is the weather channel's slot in the [channel plan](channel-plan.md). The headend passes the
script its multicast destination and restarts it if it exits. `headend.py --list`
shows it as a live channel.

### Changing the location

The forecast location is the `WEATHER_LOCATION` setting. It's currently **05443**.

1. Edit `WEATHER_LOCATION` in the `env` block above. It takes anything the WeatherStar
   search box takes:
   - a ZIP code: `"05443, USA"`. Adding `, USA` keeps the lookup from matching a postal
     code in another country;
   - a town: `"Burlington, VT"`;
   - an airport: `"Burlington International Airport"`.
2. Restart the headend (`systemctl --user restart fs42-headend`, or Ctrl-C and start it
   again). Only the weather channel picks up the change.

**Optional: pin the exact spot.** WEATHER_LOCATION is looked up through an online
geocoder each time the browser starts. To skip that lookup, also set
`WEATHER_LATLON` to the place's coordinates, e.g. `"WEATHER_LATLON": "44.1337,-73.0787"`.
You can get the coordinates by right-clicking the spot in Google Maps.
`WEATHER_LOCATION` is still used as the search-box text. If both are set,
`WEATHER_LATLON` decides where the forecast is for, so change both together.

**Choosing the location interactively:** open `http://<headend>:8042/` in a
browser while the channel is running, search for a place and check that the pages look
right. Then copy the place into `WEATHER_LOCATION`. The copy you open in your browser
is separate and doesn't change what's on air.

### Other settings

| Setting | Default | What it does |
|---|---|---|
| `WEATHER_LOCATION` | `05443, USA` | Where to forecast (see above) |
| `WEATHER_LATLON` | none | `lat,lon`. Skips the geocoder |
| `WEATHER_MUSIC` | ws4kp's `server/music` | Folder of `.mp3`, `.flac`, `.wav`, `.ogg` or `.m4a` files, shuffled and looped. It also reads one level of subfolders. ws4kp ships four copyright-free WeatherStar-style tracks, which are the fallback. With no music at all, the channel is silent. |
| `WEATHER_OPTIONS` | none | Extra ws4kp settings as a query string (below) |
| `WEATHER_BROWSER_RESTART_H` | `24` | Relaunch Chromium every N hours. The screen goes black for a few seconds while it reloads. `0` = never |
| `WS4KP_DIR` | `/opt/ws4kp` | Where ws4kp is installed |
| `WS4KP_PORT` | `8042` | Port for the local ws4kp server |
| `WEATHER_PAGE` | none | Use this page instead of the local server, e.g. `https://weatherstar.netbymatt.com/`. That's a fallback only: the channel then depends on someone else's site |
| `WEATHER_DISPLAY` | `:43` | Virtual X display. Prevue uses `:42` |
| `WEATHER_CHROMIUM` | `chromium` | Browser binary |

**Which pages play:** ws4kp's permalink parameters go in `WEATHER_OPTIONS`, joined with `&`.
For example, `"WEATHER_OPTIONS": "travel=false&almanac=true&hourly-graph=false"`.
The page names are `hazards`, `current-weather`, `latest-observations`, `hourly`,
`hourly-graph`, `travel`, `regional-forecast`, `local-forecast`, `extended-forecast`,
`almanac`, `spc-outlook` and `radar`. Each one takes `true` or `false`. `speed-select=1.25`
speeds up the cycle. To see every option, open the local page, change settings, and use
**Copy Permalink**.

The script already sets these: kiosk mode (no toolbar, starts playing at once), 4:3 rather
than widescreen, US units, and **scan lines off**, because a real CRT draws its own.

### Dot crawl on composite

Computer-drawn text has razor-sharp colour edges, and on a composite or RF TV each one
crawls with dots. The script softens only the colour detail, horizontally, down to roughly
what NTSC can carry (about 1.3 MHz). It also trims saturation slightly. Brightness stays
sharp, so the text stays crisp. The code is in `tools/crt_soften.sh`, and it's on by default.

| Setting | Default | What it does |
|---|---|---|
| `CRT_CHROMA_SIGMA` | `1.4` | Horizontal colour blur, in pixels at 720 wide. Raise it (e.g. `2`) for more softening; `0` turns it off |
| `CRT_SATURATION` | `0.9` | Saturation multiplier. `1` leaves colour saturation unchanged |

Put them in the channel's `env` block to compare on a real set. In the sandbox, a test
card of yellow and white text on WeatherStar blue kept its luma edges identical,
while its sharpest colour steps dropped by about a third.

## Test by hand

```bash
URL=/tmp/weather.ts WEATHER_SECONDS=120 bash tools/weather/weather_channel.sh    # 2 minutes to a file
ffplay /tmp/weather.ts
URL='udp://239.42.0.40:5000?pkt_size=1316&ttl=1' bash tools/weather/weather_channel.sh   # live, Ctrl-C to stop
```

To see the virtual screen while it runs, grab one frame from it:
`ffmpeg -f x11grab -video_size 640x480 -i :43 -frames:v 1 /tmp/weather.png`.

## Logs and troubleshooting

The logs are `/tmp/weather-ws4kp.log`, `/tmp/weather-chromium.log` and `/tmp/weather-xvfb.log`,
plus the script's own messages on stderr (the headend's journal when it runs as a service).

- **"port 8042 is already in use":** another ws4kp is still running. Stop it, or set `WS4KP_PORT`.
- **"display :43 is already in use":** another channel has that display. Set `WEATHER_DISPLAY`.
- **Stuck on the WeatherStar 4000+ title card:** it hasn't got any data. Check that the box can reach
  `api.weather.gov` and `geocode.arcgis.com` (or set `WEATHER_LATLON`), and check the location.
  Open the local page in a desktop browser and look for errors.
- **Wrong town:** the ZIP matched somewhere else. Add `, USA`, use `"Town, ST"`, or set `WEATHER_LATLON`.
- **Music too loud or quiet next to other channels:** normalise the music folder once, for example with
  `ffmpeg -i in.mp3 -af loudnorm=I=-23 out.mp3`.

## Load on the A10-7800

In the sandbox, the encoder used about 13% of one core. Chromium was idle on the title card.
On the A10, expect roughly double that for ffmpeg, plus Chromium's software rendering of the
scrolling pages. The punch list's A10 benchmark covers this.
