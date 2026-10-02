#!/usr/bin/env bash
# setup_vm.sh - turn a fresh Debian 13 VM into a Prevue channel test box.
#
# Run as root, OUTSIDE any venv (the Prevue pieces use only the Python standard library):
#   su -c 'bash setup_vm.sh bakacast'          (or: sudo bash setup_vm.sh bakacast)
#
# Installs FS-UAE, Xvfb, ffmpeg and friends, clones the repo for <user>, makes
# /opt/prevue for the Kickstart ROM and ADF, and installs (but doesn't start)
# the prevue-vm systemd service. Safe to re-run.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run as root: su -c 'bash $0 <user>'" >&2; exit 1; }
U="${1:-bakacast}"
id "$U" >/dev/null || { echo "no such user: $U" >&2; exit 1; }
H=$(getent passwd "$U" | cut -d: -f6)
REPO_URL="${REPO_URL:-https://github.com/Bakamoichigei/fs42-headend-stream-copy.git}"
REPO="$H/fs42-headend-stream-copy"

echo "== packages"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  sudo git python3 openssh-server systemd-timesyncd ca-certificates \
  xvfb x11-utils libgl1-mesa-dri ffmpeg fonts-dejavu-core socat telnet tcpdump
if ! DEBIAN_FRONTEND=noninteractive apt-get install -y fs-uae; then
  echo "!! fs-uae isn't installable from this Debian's repos." >&2
  echo "   Check 'apt-cache policy fs-uae' (contrib enabled?), then re-run." >&2
  exit 1
fi
dpkg-query -W -f='fs-uae ${Version}\n' fs-uae
usermod -aG sudo "$U"

echo "== clock (Prevue shows it on screen; listings are local wall-clock time)"
timedatectl set-timezone America/New_York
timedatectl set-ntp true

echo "== repo"
if [[ -d "$REPO/.git" ]]; then
  sudo -u "$U" git -C "$REPO" pull --ff-only
else
  sudo -u "$U" git clone "$REPO_URL" "$REPO"
fi

echo "== /opt/prevue (put kick204.rom and PREVUE.ADF here)"
install -d -o "$U" -g "$U" /opt/prevue /opt/prevue/music

echo "== service"
if [[ ! -f /etc/default/prevue-vm ]]; then
  cat > /etc/default/prevue-vm <<'EOF'
# Settings for prevue-vm.service (tools/prevue/prevue_channel.sh). Restart the service after editing.
URL=udp://239.42.0.42:5000?pkt_size=1316&ttl=1
CHANNEL_NAME=PREVUE
PREVUE_KICKSTART=/opt/prevue/kick204.rom
PREVUE_DISK=/opt/prevue/PREVUE.ADF
# No FS42 schedules on the VM: use the built-in demo lineup, or --listings <file.json>
PREVUE_FEED_ARGS=--demo
# Optional audio bed (any mp3/flac/wav/ogg files); leave empty for silence
PREVUE_MUSIC=
# Optional "genlock" video behind the grid (FS-UAE 3.1 can't key it itself; ffmpeg keys this colour)
PREVUE_PROMO=
PREVUE_KEY_COLOR=
PREVUE_BOOT_WAIT=25
EOF
fi
sed "s#@USER@#$U#g; s#@REPO@#$REPO#g" "$REPO/tools/prevue-vm/prevue-vm.service" \
  > /etc/systemd/system/prevue-vm.service
systemctl daemon-reload

IP=$(ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | head -1)
cat <<EOF

Done. Next (docs/prevue-vm.md):
  1. From Windows:  scp kick204.rom PREVUE.ADF $U@$IP:/opt/prevue/
  2. Bars first:    bash $REPO/tools/prevue-vm/test_pattern.sh
  3. Then Prevue:   sudo systemctl enable --now prevue-vm ; journalctl -fu prevue-vm
EOF
