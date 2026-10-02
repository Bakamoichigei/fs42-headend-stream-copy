#!/usr/bin/env bash
# test_pattern.sh - SMPTE bars + 1 kHz tone in the house format, multicast to a decoder.
#
# The first thing to send a new XTV125D: proves the multicast path, the 4:3 frame,
# the NTSC output level and the audio level before Prevue adds its own variables.
# The running timecode is there to watch for judder, freezes and recovery.
#
#   bash tools/prevue-vm/test_pattern.sh                        # -> 239.42.0.42:5000 (channel 42)
#   URL='udp://239.42.0.7:5000?pkt_size=1316&ttl=1' bash tools/prevue-vm/test_pattern.sh
#
# Runs outside any venv. Ctrl-C stops it (use that for the "stream stops" check).
set -euo pipefail
URL="${URL:-udp://239.42.0.42:5000?pkt_size=1316&ttl=1}"
LABEL="${LABEL:-BAKACAST TEST}"
FONT=/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf

echo "bars + tone -> $URL   (Ctrl-C to stop)"
exec ffmpeg -hide_banner -loglevel warning -stats -nostdin -re \
  -f lavfi -i "smptebars=size=720x480:rate=30000/1001" \
  -f lavfi -i "sine=frequency=1000:sample_rate=48000" \
  -filter_complex "[0:v]drawbox=x=200:y=40:w=320:h=80:color=black:t=fill,\
drawtext=fontfile=${FONT}:text='${LABEL}':x=(w-tw)/2:y=48:fontsize=26:fontcolor=white,\
drawtext=fontfile=${FONT}:text='%{localtime\:%H\\\\\:%M\\\\\:%S}  %{n}':x=(w-tw)/2:y=84:fontsize=26:fontcolor=white,\
setsar=8/9,setfield=tff,format=yuv420p[v];[1:a]aformat=channel_layouts=stereo[a]" \
  -map "[v]" -map "[a]" \
  -c:v mpeg2video -b:v 4500k -maxrate 6000k -bufsize 1835k -g 15 -bf 2 -flags +cgop+ilme+ildct -sc_threshold 1000000000 \
  -c:a mp2 -b:a 192k -ar 48000 -ac 2 \
  -f mpegts -muxrate 7000000 -pcr_period 20 -pes_payload_size 0 -mpegts_pmt_start_pid 0x1000 -mpegts_start_pid 0x100 \
  -metadata service_name="$LABEL" "$URL"
