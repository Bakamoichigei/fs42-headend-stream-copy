#!/usr/bin/env bash
# headend_prep.sh - transcode media into the FS42 headend "house format".
#
# Run this on the transcode machine, NOT the FS42 host. The headend
# stream-copies these files byte-for-byte (only timestamps / PIDs /
# continuity counters are rewritten), so EVERY file that airs on a channel
# must share the exact same parameters. Don't hand-tune per file.
#
# House format (what the VBrick XTV125D decodes as "MPEG2 Multicast Live"):
#   Container : MPEG-2 transport stream, 188-byte packets, CBR muxrate
#   PIDs      : PMT 0x1000, video 0x100 (carries PCR), audio 0x101
#   Video     : MPEG-2 MP@ML, 720x480, 29.97 interlaced TFF, DAR 4:3,
#               closed GOP of 15 (N=15, M=3), fixed cadence, sequence header every GOP
#   Audio     : MPEG-1 Layer II, 48 kHz stereo, 192 kb/s
#
# Usage:
#   headend_prep.sh input.mkv output.ts          # one file
#   headend_prep.sh --slate runtime/slate.ts     # 60s SMPTE bars + 1 kHz tone
#   JOBS=4 headend_prep.sh --dir /src /dst       # mirror a folder tree
#
# Tunables (env): VBITRATE (default 4500k), VMAXRATE (6000k), MUXRATE (7000000),
#                 FIELD_ORDER (tff|bff, default tff), LOUDNORM (1 = normalize to -24 LUFS)
set -euo pipefail

VBITRATE="${VBITRATE:-4500k}"
VMAXRATE="${VMAXRATE:-6000k}"
MUXRATE="${MUXRATE:-7000000}"
FIELD_ORDER="${FIELD_ORDER:-tff}"
LOUDNORM="${LOUDNORM:-1}"
JOBS="${JOBS:-2}"


# Fit anything into a 4:3 frame (pillar/letterbox), then map it onto the 720x480
# raster with the Rec.601 8:9 pixel aspect, and convert to 29.97.
#   1) undo any source anamorphic (DVD rips etc.) -> square pixels
#   2) fit inside 640x480 (square-pixel 4:3) and pad
#   3) stretch to 720x480 and flag SAR 8:9  => displays as 4:3
VF="scale=trunc(iw*sar/2)*2:ih,setsar=1,\
scale=640:480:force_original_aspect_ratio=decrease:flags=lanczos,\
pad=640:480:(ow-iw)/2:(oh-ih)/2:black,scale=720:480:flags=lanczos,setsar=8/9,\
fps=30000/1001,setfield=${FIELD_ORDER},format=yuv420p"

AF="aresample=48000,aformat=channel_layouts=stereo"
[[ "$LOUDNORM" == "1" ]] && AF="loudnorm=I=-24:TP=-2:LRA=11,${AF}"

VIDEO_OPTS=(
  -c:v mpeg2video -profile:v 4 -level:v 8
  -b:v "$VBITRATE" -maxrate "$VMAXRATE" -bufsize 1835k
  -g 15 -bf 2 -flags +cgop+ilme+ildct -alternate_scan 1
  -sc_threshold 1000000000 -intra_vlc 1 -dc 9
  -color_primaries smpte170m -color_trc smpte170m -colorspace smpte170m
  -aspect 4:3
)
AUDIO_OPTS=( -c:a mp2 -b:a 192k -ar 48000 -ac 2 )
MUX_OPTS=(
  -f mpegts -muxrate "$MUXRATE" -pcr_period 20   # pes_payload_size 0 = one audio frame per PES (clean audio cuts)
  -mpegts_pmt_start_pid 0x1000 -mpegts_start_pid 0x100
  -mpegts_flags +resend_headers -muxdelay 0.7 -pes_payload_size 0
  -metadata service_provider=FS42 -metadata service_name=FS42
)

encode_one() {
  local in="$1" out="$2"
  mkdir -p "$(dirname "$out")"
  local tmp="${out}.part"
  ffmpeg -hide_banner -nostdin -loglevel warning -y -i "$in" \
    -map 0:v:0 -map 0:a:0? -vf "$VF" -af "$AF" \
    "${VIDEO_OPTS[@]}" "${AUDIO_OPTS[@]}" "${MUX_OPTS[@]}" "$tmp"
  mv -f "$tmp" "$out"
  echo "ok  $out"
}

make_slate() {
  local out="$1"
  mkdir -p "$(dirname "$out")"
  ffmpeg -hide_banner -nostdin -loglevel warning -y \
    -f lavfi -i "smptebars=size=720x480:rate=30000/1001" \
    -f lavfi -i "sine=frequency=1000:sample_rate=48000" \
    -t 60 -vf "setsar=8/9,setfield=${FIELD_ORDER},format=yuv420p" \
    -af "volume=-20dB,aformat=channel_layouts=stereo" \
    "${VIDEO_OPTS[@]}" "${AUDIO_OPTS[@]}" "${MUX_OPTS[@]}" "$out"
  echo "ok  $out"
}

case "${1:-}" in
  --slate)
    make_slate "${2:?output path required}";;
  --dir)
    src="${2:?source dir}"; dst="${3:?dest dir}"
    find "$src" -type f \( -iname '*.mp4' -o -iname '*.mkv' -o -iname '*.avi' -o -iname '*.mov' \
         -o -iname '*.mpg' -o -iname '*.mpeg' -o -iname '*.m4v' -o -iname '*.wmv' -o -iname '*.webm' -o -iname '*.ts' \) -print0 |
    while IFS= read -r -d '' f; do
      rel="${f#"$src"/}"; out="$dst/${rel%.*}.ts"
      [[ -s "$out" && "$out" -nt "$f" ]] && continue   # already done
      printf '%s\0%s\0' "$f" "$out"
    done | xargs -0 -n2 -P "$JOBS" "$0"
    ;;
  ""|-h|--help)
    sed -n 2,26p "$0";;
  *)
    encode_one "$1" "${2:?output path required}";;
esac
