# crt_soften.sh - sourced by the live-channel scripts (weather, Prevue).
#
# Computer graphics have razor-sharp colour edges: small bright text on a saturated
# background. NTSC can't carry that much colour detail (I ~1.3 MHz, Q ~0.5 MHz), so on a
# composite/RF TV every letter edge turns into dot crawl. This softens only the colour
# (chroma) planes horizontally, to roughly NTSC's colour bandwidth, and trims saturation a
# little. Brightness (luma) stays sharp, so text stays crisp.
#
#   CRT_CHROMA_SIGMA  horizontal chroma blur in pixels at 720 wide (default 1.4 ~ 1.3 MHz; 0 = off)
#   CRT_SATURATION    saturation multiplier (default 0.9; 1 = unchanged)
#
# Sets CRT_FILTER to an ffmpeg filter fragment ending in a comma (or empty), for use
# just before the final format=yuv420p.
CRT_CHROMA_SIGMA="${CRT_CHROMA_SIGMA:-1.4}"
CRT_SATURATION="${CRT_SATURATION:-0.9}"
CRT_FILTER=""
if [[ "$CRT_CHROMA_SIGMA" != "0" || "$CRT_SATURATION" != "1" ]]; then
  CRT_FILTER="format=yuv444p,"
  [[ "$CRT_CHROMA_SIGMA" != "0" ]] && CRT_FILTER+="gblur=sigma=${CRT_CHROMA_SIGMA}:sigmaV=0:planes=6,"
  [[ "$CRT_SATURATION" != "1" ]] && CRT_FILTER+="eq=saturation=${CRT_SATURATION},"
fi
