#!/usr/bin/env bash
# prevue_channel.sh - run the emulated Prevue Guide as a live headend channel.
#
#   serial bridge  ->  FS-UAE (Prevue 9.0.4 / 7.8.3) on a virtual X display
#   prevue_feed.py ->  bridge (listings from FS42's schedules)
#   ffmpeg: grab the display [+ key it over promo video] + music -> house-format MPEG-2 TS -> $URL
#
# The headend starts this for any entry in headend.live_channels and passes
# the channel's multicast URL in $URL. Run it by hand for testing:
#   URL=udp://239.42.0.42:5000?ttl=1 tools/prevue/prevue_channel.sh
#
# Settings (environment, or headend.live_channels.<n>.env in main_config.json):
#   PREVUE_KICKSTART   Kickstart 2.04 ROM file (required - e.g. from Amiga Forever)
#   PREVUE_DISK        PREVUE.ADF, or a folder with the extracted software
#   PREVUE_MUSIC       folder of music for the audio bed (optional; silence otherwise)
#   PREVUE_PROMO       video file looped behind the Amiga graphics (optional "genlock")
#   PREVUE_KEY_COLOR   colour the genlock keys out, e.g. 0x000000 (only with PREVUE_PROMO)
#   PREVUE_DISPLAY     X display number to use (default :42)
#   CRT_CHROMA_SIGMA / CRT_SATURATION  dot-crawl softening, see tools/crt_soften.sh (default 1.4 / 0.9)
set -euo pipefail
cd "$(dirname "$0")/../.."                       # FS42 root
source tools/crt_soften.sh                       # CRT_FILTER: tame dot crawl on composite

: "${URL:?URL (multicast output) not set}"
: "${PREVUE_KICKSTART:?set PREVUE_KICKSTART to your Kickstart 2.04 ROM}"
: "${PREVUE_DISK:?set PREVUE_DISK to PREVUE.ADF or the software folder}"
DISPLAY_NUM="${PREVUE_DISPLAY:-:42}"
SERIAL=/tmp/prevue-serial
PORT="${PREVUE_PORT:-5541}"
MUXRATE="${MUXRATE:-7000000}"

pids=()
cleanup() { for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT
trap 'exit 0' INT TERM

# 1. virtual serial cable
python3 tools/prevue_serial_bridge.py --link "$SERIAL" --port "$PORT" & pids+=($!)
sleep 1

# 2. a screen for the Amiga
Xvfb "$DISPLAY_NUM" -screen 0 720x480x24 -nolisten tcp & pids+=($!)
sleep 1
export DISPLAY="$DISPLAY_NUM" SDL_AUDIODRIVER=dummy

# 3. the Amiga
if [[ -d "$PREVUE_DISK" ]]; then DISK_OPT=(--hard_drive_0="$PREVUE_DISK"); else DISK_OPT=(--floppy_drive_0="$PREVUE_DISK"); fi
fs-uae tools/prevue/prevue.fs-uae --kickstart_file="$PREVUE_KICKSTART" "${DISK_OPT[@]}" \
       --serial_port="$SERIAL" & pids+=($!)
sleep "${PREVUE_BOOT_WAIT:-20}"                   # let it boot to ER007 ("no data yet")

# 4. listings
python3 prevue_feed.py --port "$PORT" & pids+=($!)

# 5. encode to the house format and send to the channel's multicast group
VIN=(-thread_queue_size 512 -f x11grab -draw_mouse 0 -framerate 30000/1001 -video_size 720x480 -i "$DISPLAY_NUM")
if [[ -n "${PREVUE_MUSIC:-}" ]]; then
  # shuffled playlist, repeated so it never runs out (the concat demuxer can't loop itself)
  : > /tmp/prevue-music.txt
  for _ in $(seq 200); do
    find "$PREVUE_MUSIC" -maxdepth 1 -type f \( -iname '*.mp3' -o -iname '*.flac' -o -iname '*.wav' -o -iname '*.ogg' \) | shuf |
      sed "s/'/'\\\\''/g; s/^/file '/; s/$/'/" >> /tmp/prevue-music.txt
  done
  AIN=(-thread_queue_size 512 -re -f concat -safe 0 -i /tmp/prevue-music.txt)
else
  AIN=(-f lavfi -i anullsrc=r=48000:cl=stereo)
fi
if [[ -n "${PREVUE_PROMO:-}" && -n "${PREVUE_KEY_COLOR:-}" ]]; then
  PIN=(-stream_loop -1 -re -i "$PREVUE_PROMO")
  FILTER="[2:v]scale=720:480,setsar=1,fps=30000/1001[bg];[0:v]colorkey=${PREVUE_KEY_COLOR}:0.08:0.0[fg];[bg][fg]overlay=shortest=0[v]"
  MAPV="[v]"
else
  PIN=()
  FILTER="[0:v]null[v]"
  MAPV="[v]"
fi
ffmpeg -hide_banner -loglevel warning -nostdin \
  "${VIN[@]}" "${AIN[@]}" "${PIN[@]}" \
  -filter_complex "$FILTER;[v]scale=720:480,setsar=8/9,fps=30000/1001,setfield=tff,${CRT_FILTER}format=yuv420p[vo]" \
  -map "[vo]" -map 1:a \
  -c:v mpeg2video -b:v 4500k -maxrate 6000k -bufsize 1835k -g 15 -bf 2 -flags +cgop+ilme+ildct -sc_threshold 1000000000 \
  -c:a mp2 -b:a 192k -ar 48000 -ac 2 \
  -f mpegts -muxrate "$MUXRATE" -pcr_period 20 -pes_payload_size 0 -mpegts_pmt_start_pid 0x1000 -mpegts_start_pid 0x100 \
  -metadata service_name="${CHANNEL_NAME:-PREVUE}" "$URL" & pids+=($!)

# stay up while everything runs; if any piece dies, exit (cleanup stops the rest and
# the headend supervisor restarts the whole channel)
wait -n "${pids[@]}"
echo "prevue_channel: a component exited - shutting the channel down" >&2
exit 1
