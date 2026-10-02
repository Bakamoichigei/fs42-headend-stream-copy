# VBrick XTV125D decoders: one box per channel

Each headend channel gets its own VBrick XTV125D (part no. 8000-0188). The box
joins its channel's multicast group and plays it full-screen out of its composite
output, which feeds that channel's modulator. There's no channel guide and no
server: the box runs in **Local Fullscreen Mode** from a `channels.xml` holding one stream.

```
headend.py ─► 239.42.0.7:5000 ─► switch (IGMP) ─► XTV125D "ch 7" ─► composite ─► ch 7 modulator
```

This is based on VBrick's quick-start manual for the 8000-0188. Nothing here has been
tried on a real box yet. [First box: things to check](#first-box-things-to-check) lists what to confirm.

## Before you buy

- **Make sure the remote is included.** The setup menu is only reachable from the remote,
  while the box is booting. After setup, the box needs nothing else.
- Make sure the power adapter is included.

## 1. Make the channels files

On the headend box, from the repo:

```bash
python3 tools/xtv125d/make_channels_xml.py          # channels 2–13, 40, 42 -> runtime/xtv125d/chNN/channels.xml
python3 tools/xtv125d/make_channels_xml.py -c 42     # e.g. the channel 42 spare
```

It reads the `headend` block of `confs/main_config.json`, so each file points at exactly the
group and port `headend.py` sends to, including any per-channel overrides. Each file looks
like this:

```xml
<?xml version="1.0" encoding="utf-8"?>
<STBLocalUI>
  <Title>Bakacast</Title>
  <GlobalMsg></GlobalMsg>
  <FullScreen>1</FullScreen>
  <AutoChannelNumbers>0</AutoChannelNumbers>
  <Stream>
    <ProgramName>BAKACAST 7</ProgramName>
    <Message>tv://239.42.0.7:5000</Message>
    <URL>tv://239.42.0.7:5000</URL>
    <DfltStrm>x</DfltStrm>
    <Channel>7</Channel>
  </Stream>
</STBLocalUI>
```

- `tv://group:port` is the manual's form for an MPEG-2 transport stream multicast.
- `FullScreen` `1` is Local Fullscreen Mode. `0` would be Local Mode, which shows the box's own channel guide.
- Keep the headend on `"encapsulation": "udp"` (the default). The manual's `tv://` examples are raw UDP.
- **`DfltStrm`** (confirmed from the box's sample): an element *inside* `<Stream>` marking the
  stream played at power-on. VBrick's sample uses the value `x` (with a malformed closing tag,
  `<DfltStrm>x<DfltStrm>`, which the box evidently tolerates). The generator writes `<DfltStrm>x</DfltStrm>`.
  If the box ignores it, try VBrick's malformed form verbatim.
- `<Channel>` and `<AutoChannelNumbers>0</AutoChannelNumbers>` are also copied from the sample.

## 2. Setup menu (once per box, with the remote)

1. Connect the box's Ethernet port to the decoder switch, its composite output to a TV or to
   the channel's modulator, and power it on.
2. While the animated **"Starting"** circle is on screen, keep pressing the remote's **Help (?)**
   button until the **Password** page appears. The manual also describes this as the unlabeled third
   button down on the right. The password is `1234`. (The **Info** icon at the lower left shows
   the MAC address without a password.)
3. **Network:** DHCP is on by default. Give the box a fixed address instead, either statically
   here or as a DHCP reservation, so you can always find it. A pattern that's easy to remember
   puts the channel in the last digits: ch 7 → `192.168.10.107`, ch 42 → `192.168.10.142`
   (adjust to the decoder network's subnet).
4. **Start Mode:** **Local**.
5. **Output:** set **SD Output** to **NTSC**, and **HD Output Configuration** to **480i**.
   The factory default is 720p. The manual says both outputs must be NTSC-family or both
   PAL, never mixed.
6. **Upgrade URL:** leave it blank. The box checks it at every boot.
7. **OK → Finish.** The box saves the settings and reboots.

## 3. Load the channels file

Serve the files from the headend box:

```bash
python3 -m http.server 8000 --directory runtime/xtv125d
```

Then telnet to the decoder (user `iptv`, password `settopbox`):

```sh
cd /root/data
cat channels.xml                  # the first time: look at VBrick's sample (and its DfltStrm line)
cp channels.xml channels.xml.orig
wget -O channels.xml http://<headend-ip>:8000/ch07/channels.xml
reboot
```

If this `wget` doesn't take `-O`, run `rm channels.xml` first, then `wget http://<headend-ip>:8000/ch07/channels.xml`.
You can also edit it in place with `vi channels.xml`. The box should boot straight into full-screen video.

## Bench test (before the A10 and the headend exist)

**Easiest:** the Prevue test VM ([prevue-vm.md](prevue-vm.md)) has `tools/prevue-vm/test_pattern.sh`
(bars, tone and a running clock in the house format), then the live Prevue channel.

A box can be tested as soon as it arrives. Any PC with ffmpeg can loop a house-format file at it:

```bash
ffmpeg -re -stream_loop -1 -i slate.ts -c copy -f mpegts "udp://239.42.0.7:5000?pkt_size=1316&ttl=1"
```

Use `slate.ts` from `tools/headend_prep.sh --slate`, or any file made by `headend_prep.sh`.
On a PC with more than one network adapter, add `&localaddr=<that PC's IP on the decoder network>`.
One stream on a plain switch is fine for this test. The full 12-channel headend needs IGMP snooping.

## First box: things to check

- [ ] It boots straight into full-screen video with no guide (confirms `FullScreen`/`DfltStrm`).
- [ ] The picture is **4:3 full frame**, not pillarboxed or stretched. The source is 720×480 with SAR 8:9.
- [ ] Motion is smooth, with no judder or combing (field order is preserved through to composite).
- [ ] The audio level is sensible against the modulator's audio input.
- [ ] **The stream stops** (stop ffmpeg): does it hold the last frame, go black, or show a message?
- [ ] **The stream comes back:** does it recover on its own, without a reboot? This matters for headend restarts.
- [ ] **Power cut:** does it come back up playing its channel with nobody touching it?
- [ ] **Decoder delay:** clap on camera, or compare against a clock. This sets `schedule_lead_s` in the headend config (default 0.7 s).
- [ ] Composite output level: 1 V p-p into 75 Ω on the scope, before it goes into the modulator.

## Manuals and references

VBrick's own support portal is login-only and blocks fetching, and no full admin guide for this box
turns up publicly. What exists:

| Document | Where | Notes |
|---|---|---|
| **Quick Start Manual, Multi-Format Set Top Box v2.2.5** (67 pp.) | [ManualsLib](https://www.manualslib.com/manual/1146852/Vbrick-8000-0188.html) (no PDF download) | The source for this page. Getting Started p. 7, Configuration p. 15, channel guide (`channels.xml`) p. 23, software upgrade p. 38, remote p. 46–51, `config.txt` reference around p. 56–58. |
| Datasheet, 8000-0188 | [av-iq (PDF)](http://cdn-docs.av-iq.com/dataSheet/8000-0188_Datasheet.pdf) | Specs only. |
| Older VBrick EtherneTV STB v3.7.3b quick start | [av-iq (PDF)](http://cdn-docs.av-iq.com/dataSheet/EthernetSTB.pdf) | Different, older box; useful background on VBrick's STB conventions. |

### Read the box's own documentation

The box carries working examples of every file it reads. Before changing anything on the first box,
telnet in (user `iptv`, password `settopbox`) and capture them:

```sh
uname -a; cat /proc/cpuinfo; cat /proc/version     # what it actually is (the XTV125 appears to be an OEM box)
ls -la /root/data /root /etc
cat /root/data/channels.xml                        # VBrick's sample, including the DfltStrm line
cat /root/data/config.txt 2>/dev/null || find / -name 'config.txt' 2>/dev/null
ps                                                 # what's running (the player, the browser)
```

Copy the output into a text file and add the answers here (especially `DfltStrm` and the `config.txt`
location). If `ftp` or `tftp` exists on the box, pulling the files whole is even better.

## What's inside (first box, 2026-10-01)

From an SSH session on the first box. **SSH works as well as telnet**, same login (`iptv` / `settopbox`),
and that login **is root** (uid 0).

| | |
|---|---|
| SoC | **Broadcom BCM7405** (dual BMIPS4380 @ 400 MHz), 314 MB RAM. Decodes MPEG-2 and H.264 in hardware |
| OS | Linux 2.6.18 (Broadcom STB kernel), BusyBox 1.11.1, built 2013-09-24 |
| Firmware | `config.txt` version **v2.5.1-vbk** (the quick start covers v2.2.5) |
| UI / player | **`stb_galio`**, ANT Galio browser-based middleware; OEM pages in `/root/titanium/demo_page/kumat/` |
| Services | `dropbear` (SSH, 22), `utelnetd` (23), a web service on **port 80**, `ntpclient` → pool.ntp.org, DHCP |
| Storage | `/` and `/root/titanium` are read-only cramfs; **`/root/data` is writable flash (jffs2, ~2.3 MB free)** and holds every setting |
| Tools | `wget`, `tftp`, `vi`; no `nc`, no `ftp` |

**`/root/data`:** `channels.xml`, `config.txt`, `adjust.xml`, `himi.xml`, `env.cfg`, `passwd` (`/etc/passwd`
links here), `setChannel`, `setVolume`, `stb.db`, `rc.d/` (`rc80.user` runs at boot), `log/`,
`mcast_source_list.conf` (empty), and **`do_not_update_config`** (an empty flag file; keep it).

### `config.txt` (confirmed location `/root/data/config.txt`)

`stb_galio` is started with `--config /root/data/config.txt`. The settings that matter here:

| Key | Factory | Want | Why |
|---|---|---|---|
| `stb.hd.outputformat` | `720p` | `480i/ntsc` | The manual says HD and SD must be the same family |
| `stb.sd.outputformat` | `ntsc` | `ntsc` | |
| `stb.sd.ar` / `stb.hd.ar` | `Full_screen` | `Full_screen` | 4:3 source fills the 4:3 raster; check on the first test |
| `stb.stm.deinterlace` | `0` | `0` | Keep fields intact through to composite |
| `stb.sd.saturation` / `contrast` / `brightness` / `hue` | `50` (0–100) | `50` | Per-box trims if the scope or the BVM says one is off |
| `stb.stm.check_av` | `auto` | `auto` | Decoder health monitor; part of what happens when a stream stops |
| `stb.stm.pattimeout` / `pmttimeout` | `600` ms | `600` | The headend sends PAT/PMT often enough |
| `stb.url.fwupg` | `http://172.17.1.5/upg/...` | empty | Checked at boot; a dead address only costs boot time |
| `stb.wdt.disable` / `timeout` | `0` / `60` s | as is | Hardware watchdog: a hung player reboots the box |
| `stb.closecaption.enable` | `1` | `1` | Line-21 captions pass through if the files carry them |
| `stb.sap.transmit.enable` | `1` | `0` | Announces the box to 224.2.133.134 every 10 s; noise |
| `stb.ezcontroller.*`, `stb.remotemgmt.*` | enabled | `0` once set up | Network remote control and IR-key simulation (see below) |
| `stb.webservice.enable` | `1` | decide later | Port-80 web UI, probably a settings page |
| `stb.remote` | `1` (NEC) | as is | |

Everything below the file's **CUT LINE** must not be edited.

### Security (do this before 14 of them are on the network)

- **Root with a published password, telnet open, SSH open, a web UI, network remote control, IR
  simulation and "go to URL" remote management** are all on by default.
- The first box picked up a **public IPv6 address** from the router as well as `10.0.0.52`. Most
  routers block inbound IPv6 by default, but don't rely on it.
- Plan: a separate VLAN or switch for the decoders with no route out (it also keeps 85 Mb/s of multicast
  off the home network), change the password (`passwd`; the file lives in `/root/data`), and turn off
  telnet and the remote-management features once the boxes are set up.

### Still to look at

- `setChannel`, `setVolume`, `rc.d/rc80.user`, `env.cfg`, `adjust.xml`, `himi.xml`, `/etc/app-version`.
- The web UI at `http://<box>/`.
- Whether `ezController` (unicast port 9095) or IR simulation can drive the setup menu, so the other
  13 boxes don't need the remote.
