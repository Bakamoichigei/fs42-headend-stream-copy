#!/usr/bin/env bash
# weather_channel.sh - WeatherStar 4000+ as a live headend channel.
#
#   ws4kp (local Node server)  ->  Chromium, kiosk mode, on a virtual X display (640x480)
#   ffmpeg: grab the display + shuffled music bed -> house-format MPEG-2 TS -> $URL
#
# The headend starts this for any entry in headend.live_channels and passes the
# channel's multicast URL in $URL. Run it by hand for testing:
#   URL=udp://239.42.0.3:5000?ttl=1 bash tools/weather/weather_channel.sh
#   URL=/tmp/weather.ts WEATHER_SECONDS=120 bash tools/weather/weather_channel.sh   # record 2 min to a file
#
# Settings (environment, or headend.live_channels.<n>.env in main_config.json):
#   WEATHER_LOCATION   what to forecast: ZIP, "City, ST" or an airport (default "05443, USA")
#   WEATHER_LATLON     optional "lat,lon" for that place; skips the geocoder lookup
#   WEATHER_OPTIONS    extra ws4kp settings as a query string, e.g. "travel=false&radar=true"
#   WS4KP_DIR          the ws4kp checkout (default /opt/ws4kp)
#   WS4KP_PORT         port for the local ws4kp server (default 8042)
#   WEATHER_PAGE       use this page instead of starting ws4kp, e.g. https://weatherstar.netbymatt.com/
#   WEATHER_MUSIC      folder of music for the bed (default: ws4kp's server/music; silence if empty)
#   WEATHER_BROWSER_RESTART_H  relaunch Chromium every N hours to shed memory (default 24, 0 = never)
#   WEATHER_DISPLAY    X display to use (default :43)
#   WEATHER_CHROMIUM   browser binary (default: chromium, then chromium-browser)
#   WEATHER_SECONDS    stop after N seconds (testing)
set -euo pipefail
cd "$(dirname "$0")/../.."                       # FS42 root

: "${URL:?URL (multicast output) not set}"
LOCATION="${WEATHER_LOCATION:-05443, USA}"
WS4KP_DIR="${WS4KP_DIR:-/opt/ws4kp}"
WS4KP_PORT="${WS4KP_PORT:-8042}"
DISPLAY_NUM="${WEATHER_DISPLAY:-:43}"
RESTART_H="${WEATHER_BROWSER_RESTART_H:-24}"
MUXRATE="${MUXRATE:-7000000}"
W=640 H=480                                       # WeatherStar's native 4:3 frame
PROFILE="$(mktemp -d /tmp/weather-chromium.XXXXXX)"

CHROMIUM="${WEATHER_CHROMIUM:-}"
if [[ -z "$CHROMIUM" ]]; then
  CHROMIUM="$(command -v chromium || command -v chromium-browser || true)"
fi
[[ -n "$CHROMIUM" ]] || { echo "weather_channel: chromium not found (apt install chromium)" >&2; exit 1; }

pids=()
browser_pid=""
cleanup() {
  [[ -n "$browser_pid" ]] && kill "$browser_pid" 2>/dev/null || true
  for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done
  rm -rf "$PROFILE"
}
trap cleanup EXIT
trap 'exit 0' INT TERM

log() { echo "weather_channel: $*" >&2; }

# 1. WeatherStar itself
if [[ -n "${WEATHER_PAGE:-}" ]]; then
  BASE="$WEATHER_PAGE"
else
  [[ -f "$WS4KP_DIR/index.mjs" ]] || { log "no ws4kp at $WS4KP_DIR (see docs/weather.md)"; exit 1; }
  BASE="http://127.0.0.1:${WS4KP_PORT}/"
  if curl -s -o /dev/null "$BASE"; then
    log "port $WS4KP_PORT is already in use (another ws4kp?); set WS4KP_PORT"; exit 1
  fi
  if [[ -f "$WS4KP_DIR/dist/index.html" ]]; then MODE=(DIST=1); else MODE=(); fi
  ( cd "$WS4KP_DIR" && exec env "${MODE[@]}" WS4KP_PORT="$WS4KP_PORT" node index.mjs ) > /tmp/weather-ws4kp.log 2>&1 &
  ws_pid=$!
  pids+=($ws_pid)
  for _ in $(seq 60); do
    kill -0 "$ws_pid" 2>/dev/null || break
    curl -fs -o /dev/null "$BASE" && break
    sleep 0.5
  done
  if ! kill -0 "$ws_pid" 2>/dev/null || ! curl -fs -o /dev/null "$BASE"; then
    log "ws4kp didn't start; see /tmp/weather-ws4kp.log"; exit 1
  fi
fi

# the page URL: kiosk (no toolbar, starts playing), 4:3, no fake scan lines (it's a real CRT)
enc() { python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "$1"; }
QS="kiosk=true&wide=false&enhanced=false&scanLines=false&units-select=us&latLonQuery=$(enc "$LOCATION")"
if [[ -n "${WEATHER_LATLON:-}" ]]; then
  IFS=, read -r LAT LON <<< "${WEATHER_LATLON// /}"
  QS+="&latLon=$(enc "{\"lat\":$LAT,\"lon\":$LON}")"
fi
[[ -n "${WEATHER_OPTIONS:-}" ]] && QS+="&${WEATHER_OPTIONS}"
PAGE="${BASE}?${QS}"
log "page: $PAGE"

# 2. a screen for the browser
DNUM="${DISPLAY_NUM#:}"
if [[ -e "/tmp/.X${DNUM}-lock" ]]; then
  if kill -0 "$(tr -d ' ' < "/tmp/.X${DNUM}-lock")" 2>/dev/null; then
    log "display $DISPLAY_NUM is already in use (set WEATHER_DISPLAY to another one)"; exit 1
  fi
  rm -f "/tmp/.X${DNUM}-lock" "/tmp/.X11-unix/X${DNUM}"      # left over from a crash
fi
Xvfb "$DISPLAY_NUM" -screen 0 ${W}x${H}x24 -nolisten tcp -nocursor > /tmp/weather-xvfb.log 2>&1 & pids+=($!)
for _ in $(seq 50); do [[ -S "/tmp/.X11-unix/X${DNUM}" ]] && break; sleep 0.2; done
[[ -S "/tmp/.X11-unix/X${DNUM}" ]] || { log "Xvfb didn't start; see /tmp/weather-xvfb.log"; exit 1; }
export DISPLAY="$DISPLAY_NUM"

# 3. the browser (relaunched if it dies, and every RESTART_H hours; ffmpeg keeps running)
BROWSER_OPTS=(--kiosk --window-position=0,0 --window-size=${W},${H} --force-device-scale-factor=1
  --user-data-dir="$PROFILE" --no-first-run --no-default-browser-check --noerrdialogs
  --disable-infobars --disable-session-crashed-bubble --disable-translate --disable-features=Translate
  --hide-scrollbars --mute-audio --disable-gpu --password-store=basic
  --disable-background-networking --disable-component-update --disable-sync --disable-default-apps
  --disable-background-timer-throttling --disable-renderer-backgrounding --disable-backgrounding-occluded-windows)
[[ $EUID -eq 0 ]] && BROWSER_OPTS+=(--no-sandbox)
start_browser() {
  "$CHROMIUM" "${BROWSER_OPTS[@]}" "$PAGE" > /tmp/weather-chromium.log 2>&1 &
  browser_pid=$!
  browser_started=$SECONDS
}
start_browser

# 4. music bed: shuffled playlist, repeated so it never runs out
MUSIC="${WEATHER_MUSIC:-$WS4KP_DIR/server/music}"
: > /tmp/weather-music.txt
if [[ -d "$MUSIC" ]]; then
  for _ in $(seq 200); do
    find "$MUSIC" -maxdepth 2 -type f \( -iname '*.mp3' -o -iname '*.flac' -o -iname '*.wav' -o -iname '*.ogg' -o -iname '*.m4a' \) | shuf |
      sed "s/'/'\\\\''/g; s/^/file '/; s/$/'/" >> /tmp/weather-music.txt
  done
fi
if [[ -s /tmp/weather-music.txt ]]; then
  AIN=(-thread_queue_size 512 -re -f concat -safe 0 -i /tmp/weather-music.txt)
else
  log "no music found in $MUSIC; sending silence"
  AIN=(-f lavfi -i anullsrc=r=48000:cl=stereo)
fi

# 5. encode to the house format and send to the channel's multicast group
DUR=()
[[ -n "${WEATHER_SECONDS:-}" ]] && DUR=(-t "$WEATHER_SECONDS")
ffmpeg -hide_banner -loglevel warning -nostdin \
  -thread_queue_size 512 -f x11grab -draw_mouse 0 -framerate 30000/1001 -video_size ${W}x${H} -i "$DISPLAY_NUM" \
  "${AIN[@]}" \
  -filter_complex "[0:v]scale=720:480:flags=lanczos,setsar=8/9,fps=30000/1001,setfield=tff,format=yuv420p[vo];[1:a]aresample=48000,aformat=channel_layouts=stereo[ao]" \
  -map "[vo]" -map "[ao]" "${DUR[@]}" \
  -c:v mpeg2video -b:v 4500k -maxrate 6000k -bufsize 1835k -g 15 -bf 2 -flags +cgop+ilme+ildct -sc_threshold 1000000000 \
  -c:a mp2 -b:a 192k -ar 48000 -ac 2 \
  -f mpegts -muxrate "$MUXRATE" -pcr_period 20 -pes_payload_size 0 -mpegts_pmt_start_pid 0x1000 -mpegts_start_pid 0x100 \
  -metadata service_name="${CHANNEL_NAME:-WEATHER}" "$URL" &
ffmpeg_pid=$!
pids+=($ffmpeg_pid)

# stay up while ffmpeg and the server run; look after the browser ourselves
while kill -0 "$ffmpeg_pid" 2>/dev/null; do
  for p in "${pids[@]}"; do
    kill -0 "$p" 2>/dev/null || { log "a component exited - shutting the channel down"; exit 1; }
  done
  if ! kill -0 "$browser_pid" 2>/dev/null; then
    log "browser exited - relaunching"
    start_browser
  elif (( RESTART_H > 0 && SECONDS - browser_started > RESTART_H * 3600 )); then
    log "scheduled browser relaunch"
    kill "$browser_pid" 2>/dev/null || true
    wait "$browser_pid" 2>/dev/null || true
    start_browser
  fi
  sleep 5
done
wait "$ffmpeg_pid" && exit 0     # WEATHER_SECONDS test run finished
log "ffmpeg exited - shutting the channel down"
exit 1
