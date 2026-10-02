# Prevue test VM: the guide channel into the first XTV125D

A throwaway Debian 13 VM on the desktop PC (VirtualBox) that runs the real Prevue channel
chain, `tools/prevue/prevue_channel.sh`, and multicasts it to the XTV125D on channel 42's
group. It stands in for the A10 until that box is built, and it's the first real test of
the **FS-UAE** half of the Prevue setup (so far only WinUAE has run Prevue).

```
Windows desktop
└─ VirtualBox VM "bakacast-prevue" (bridged onto the wired LAN)
   ├─ FS-UAE (A500+, KS 2.04, PREVUE.ADF) on Xvfb :42  ◄─ pty ◄─ prevue_serial_bridge ◄─ prevue_feed.py --demo
   └─ ffmpeg: x11grab → MPEG-2 house format → udp://239.42.0.42:5000
                                                      │ home switch
                                                      ▼
                                          XTV125D → composite → TV / MICM ch 42
```

## What you need

- **VirtualBox 7.1 or later** on the desktop. If Hyper-V or "Virtual Machine Platform" is on,
  VirtualBox still runs but slower; cycle-exact 68000 emulation is light, so that's fine.
- **Debian 13 netinst ISO** (amd64) from debian.org.
- **Kickstart 2.04 (37.175)** and **PREVUE.ADF**, the same files WinUAE uses.
- The **desktop on Ethernet.** Bridging over Wi-Fi mangles MAC addresses and multicast.
- The XTV125D on the same switch or router, plus its remote.

## 1. Push the scripts first

The VM clones the repo from GitHub, so commit and push these files from GitHub Desktop
before step 3 (or the clone won't have `tools/prevue-vm/`).

## 2. Make the VM (Windows, PowerShell, no admin)

```powershell
cd X:\GitHub\fs42-headend-stream-copy
powershell -ExecutionPolicy Bypass -File tools\prevue-vm\create_vm.ps1 -Iso C:\path\to\debian-13.x.x-amd64-netinst.iso
```

- It bridges onto whichever adapter has the default route. If it picks the wrong one it
  lists the choices; re-run with `-Adapter "<name>"`.
- 4 vCPUs, 4 GB RAM, 20 GB disk. The user is `bakacast` / `bakacast` (change it with `-Password`).
- The install is unattended and takes 10–20 minutes. **If the unattended step errors**, start the VM
  with the ISO attached and install by hand: in the software selection, tick only
  **SSH server** and **standard system utilities**.

## 3. Set it up (inside the VM, outside any venv)

Log in on the VM console, then:

```bash
ip -4 addr show                      # note the VM's LAN address (e.g. 192.168.1.60)
su -                                 # root password = the user password with the unattended install
apt install -y git && git clone https://github.com/Bakamoichigei/fs42-headend-stream-copy.git /tmp/fs42
bash /tmp/fs42/tools/prevue-vm/setup_vm.sh bakacast
exit
```

From here on SSH in from Windows instead (`ssh bakacast@<VM IP>`); it's easier to copy and paste.

`setup_vm.sh` installs FS-UAE, Xvfb, ffmpeg and the tools, sets the clock to America/New_York with
NTP on, clones the repo to `~/fs42-headend-stream-copy`, makes `/opt/prevue`, and installs
`prevue-vm.service` (not started). **Log out and back in** once so `sudo` works.

## 4. Copy the Amiga files in (Windows)

```powershell
scp "C:\path\to\kick204.rom" "C:\path\to\PREVUE.ADF" bakacast@<VM IP>:/opt/prevue/
```

Use the names exactly as in `/etc/default/prevue-vm` (`kick204.rom`, `PREVUE.ADF`), or edit that file.
**Use a copy of the ADF** that WinUAE isn't also writing to.

## 5. Prepare the XTV125D

Follow [xtv125d.md](xtv125d.md) §2 (setup menu: Local, NTSC, 480i, a fixed IP), then load the
channel 42 file, served from the VM:

```bash
cd ~/fs42-headend-stream-copy
python3 tools/xtv125d/make_channels_xml.py -c 42          # -> runtime/xtv125d/ch42/channels.xml (tv://239.42.0.42:5000)
python3 -m http.server 8000 --directory runtime/xtv125d    # leave running; Ctrl-C when the box has it
```

and in another SSH window, `telnet <decoder IP>` (user `iptv`, password `settopbox`) and follow
[xtv125d.md](xtv125d.md) §3 with `http://<VM IP>:8000/ch42/channels.xml`. **Before you replace
anything, save the box's own files** (see "Read the box's own documentation" in xtv125d.md).

## 6. Bars first

```bash
bash ~/fs42-headend-stream-copy/tools/prevue-vm/test_pattern.sh
```

SMPTE bars, a 1 kHz tone at −18 dBFS, and a running clock with a frame counter, in exactly the house
format the headend sends. Work through the "First box: things to check" list in
[xtv125d.md](xtv125d.md) with this running: 4:3 framing, smooth motion, audio level, then **Ctrl-C**
for the stream-stops test and start it again for recovery. To aim it at another group:
`URL='udp://239.42.0.7:5000?pkt_size=1316&ttl=1' bash tools/prevue-vm/test_pattern.sh`.

## 7. Then Prevue

```bash
sudo systemctl enable --now prevue-vm
journalctl -fu prevue-vm             # Ctrl-C stops watching, not the channel
```

About 25 s after start the demo lineup is sent; the grid fills in over the next minute or two
(the feeder is paced like a 2400-baud line). Settings live in `/etc/default/prevue-vm`; after editing,
`sudo systemctl restart prevue-vm`.

| Setting | What it's for |
|---|---|
| `PREVUE_FEED_ARGS` | `--demo` (built in), or `--listings /opt/prevue/lineup.json` for your own lineup |
| `PREVUE_MUSIC` | A folder of music for the audio bed, e.g. `/opt/prevue/music` |
| `PREVUE_PROMO` + `PREVUE_KEY_COLOR` | Video behind the grid, keyed on a colour (e.g. `0x000000`) |
| `PREVUE_BOOT_WAIT` | Seconds to let the Amiga boot before the feeder starts |
| `URL` | Where it's sent. Keep `pkt_size=1316` (7 TS packets per datagram) |

**Seeing the Amiga screen without the decoder:** `ffplay udp://239.42.0.42:5000` on any PC on the LAN
(add `?localaddr=<that PC's IP>` if it has several adapters), or VLC → Open Network Stream →
`udp://@239.42.0.42:5000`.

## FS-UAE: what's different from the WinUAE setup

Checked against the FS-UAE 3.1.66 source (the version Debian ships):

- **Genlock "connected" is supported** (`genlock`, modes `none`/`noise`/`testcard`), which is what
  stops Prevue going black after the boot CLI. So the software *should* run.
- **No `genlock_alpha` and no video-file genlock source** (those arrived in later WinUAE cores). The
  grid's transparent areas come out black, and a promo video behind it has to be keyed in ffmpeg
  (`PREVUE_PROMO` + `PREVUE_KEY_COLOR=0x000000`). That keys real black too, so expect some holes;
  it's a fallback, not the final look.
- **Serial via a pseudo-terminal** is a documented FS-UAE route (its docs test it with socat), which is
  what `prevue_serial_bridge.py` provides.

## If it doesn't work

| Symptom | Look at |
|---|---|
| The XTV125D shows nothing, even with bars | `sudo tcpdump -ni any host 239.42.0.42` on the VM shows packets leaving? Then on Windows, check that the VM's NIC is **bridged** to the Ethernet adapter (not NAT). Some routers drop multicast between ports with IGMP snooping and no querier; test with the box and PC on one dumb switch. |
| Bars work, Prevue is black | `journalctl -u prevue-vm`: did FS-UAE start? Is the ROM found? If FS-UAE runs but Prevue stalls, the genlock option wasn't honoured: report it, and the fallback is WinUAE under Wine in the same VM. |
| Grid shows ER007 forever | The feeder isn't getting through: is `prevue_serial_bridge.py` running (`pgrep -af prevue`)? |
| Clock is off | `timedatectl` should say "System clock synchronized: yes". |
| Choppy picture | `top` in the VM: FS-UAE plus ffmpeg should sit well under 2 cores. Give the VM more CPUs if not. |

## When the A10 is up

Nothing here is VM-specific except `create_vm.ps1`. On the A10, the same channel runs from the headend's
`live_channels` (see [prevue.md](prevue.md)), and the VM can be deleted.
