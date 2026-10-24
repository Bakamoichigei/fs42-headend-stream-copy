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

**Box 1's provenance:** US government surplus. Under the front film is a property tag:
"Org Name: FORT BELVOIR COMM", "Nomen: VIDEO IMAGE PROCES", SN AW0741251980. Keep the tag on. Its
software is factory default (VBrick's sample `channels.xml` and the OEM's demo files), so it was most
likely never deployed. It's earmarked as the **channel 42 (Prevue)** decoder.

From an SSH session on the first box. **SSH works as well as telnet**, same login (`iptv` / `settopbox`),
and that login **is root** (uid 0).

| | |
|---|---|
| SoC | **Broadcom BCM7405** (dual BMIPS4380 @ 400 MHz), 314 MB RAM. Decodes MPEG-2 and H.264 in hardware |
| OS | Linux 2.6.18 (Broadcom STB kernel), BusyBox 1.11.1, built 2013-09-24 |
| Firmware | **1255.1501.0022.8068**, bootloader 2.22.23, middleware 2.1.4, browser 3.1.8.24.04.20, built 2013-09-24 (`/etc/app-version`); `config.txt` version **v2.5.1-vbk** (the quick start covers v2.2.5) |
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

### From the `/root/data` backup (2026-10-23)

**Back up a box (Windows cmd; PowerShell's `>` corrupts binary):**
`ssh vbrick "tar cf - /root/data" > %USERPROFILE%\Desktop\xtv125d-data.tar`.
The 2013 dropbear needs old algorithms, so `%USERPROFILE%\.ssh\config` has:

```
Host vbrick 10.0.0.52
    HostName 10.0.0.52
    User iptv
    KexAlgorithms +diffie-hellman-group14-sha1
    HostKeyAlgorithms +ssh-rsa
    MACs +hmac-sha1
```

The first box's factory `/root/data` is kept as the baseline for all 14.

- **A virtual remote over SSH: `gotourl <code>`** presses a remote key (needs
  `stb.remotemgmt.irsim.enable: 1`, which is on). Codes are NEC, address `0x708f`, then the key byte and
  its complement: digits `0x708f00ff` … `0x708f09f6` (key byte 0x00–0x09), **OK/Enter `0x708f16e9`**,
  Vol+ `0x708f0ff0`, Vol− `0x708f0ef1`. VBrick's `setChannel` and `setVolume` scripts are just sequences
  of these. Other keys (Help, arrows, Menu) are still to map.
- **`env.cfg` is the setup menu's store**: binary records of `[id u32 LE][length u32 LE][value]`.
  Decoded: NTP server `pool.ntp.org` (id 251), time zone **`+8`** (252, i.e. Taiwan/China factory
  default), **password `1234`** (202), a **second password `5678`** (203; probably an engineering
  menu), an IP field `0.0.0.0` (351), and small integers at ids 101, 151, 107, 157, 301, 311 (=22),
  312 (=23), 352, 353 whose meaning is unknown.
  **To decode the rest:** change one thing in the remote's setup menu, back up again, compare.
  Once the start-mode and output fields are known, the other boxes can be set up by copying
  `env.cfg` + `config.txt` + `channels.xml` over SSH, without the remote. Use DHCP reservations, not static IPs, so copied files can't collide.
- **`rc.d/rc80.user`** starts the UI at boot (`cd /root/titanium; settop install; galio initrc &`).
  It's a hook for our own boot-time lines later; a mistake there can leave the box without its player
  (SSH still comes up), so test it on one box only.
- **`himi.xml`**: an OEM demo channel list showing **per-stream decoder options**:
  `<Decode prm="deInterlace">`, `"rtp"`, `"check_av"`, `"decode_mode"`, `"tsm_mode"` (Broadcom
  timestamp management, i.e. how it locks to PCR), `"drm"` and `"src"` (source-specific multicast).
  Whether `channels.xml` honours `<Decode>` is untested. Keep it in mind if lip-sync or splices misbehave.
- **`passwd`**: both `root` and `iptv` are uid 0 with password logins. Change both.
- **Volume is at 100** (`cookies.txt`: `tvVolValue 100`). Leave it there and set audio levels at the modulator.
- `stb.db` is an empty SQLite download-manager table; `mcast_source_list.conf` is empty.

### Full flash backup (box 1, verified 2026-10-24)

Dump each partition from **cmd** (PowerShell's `>` corrupts binary), using the raw `/dev/mtdN` devices:
`mtdblock` rounds reads down to 512-byte blocks and truncated `config`, `nvram` and `cert`, and gave a
bad `appfs`.

```
for /L %i in (0,1,10) do ssh vbrick "cat /dev/mtd%i" > %USERPROFILE%\Desktop\xtv125d-mtd%i.bin
ssh vbrick "for i in 0 1 2 3 4 5 6 7 8 9 10; do md5sum /dev/mtd$i; done"
```

Check on the PC (PowerShell is fine for hashing):
`Get-ChildItem $HOME\Desktop\xtv125d-mtd*.bin | Get-FileHash -Algorithm MD5`.

| mtd | Name | Size | MD5 (box 1) | Same on every box? |
|---|---|---:|---|---|
| 0 | rootfs | 6,815,744 | `5354027012285e9a8a98bc668e265388` | expected |
| 1 | cfe (bootloader) | 1,048,576 | `22927d7e9a9a726b57ab0b062939296d` | expected |
| 2 | vmlinux | 2,359,296 | `80df22043fa5b2c6a0655be8ce6d8be7` | expected |
| 3 | config | 144 | `4d72adef251757c5685a1d2cf18572bf` | **no** (per-box; likely MAC) |
| 4 | nvram | 1,904 | `14af06e6c560a6712701accf773077d7` | **no** (per-box) |
| 5 | appfs | 18,989,056 | `dd8ca6b8abafc28f6635c7c544e63555` | expected |
| 6 | data (`/root/data`) | 3,014,656 | `249fb6ff37b4f778616d4931d930865f` | no (settings; changes in use) |
| 7 | image | 28,966,912 | `a4b71ddcba79bad5815cbe7eeddb80af` | expected |
| 8 | cert | 129,008 | `6e718efcc86a9ea987dc1ef5c0bdf45e` | **no** (probably per-box) |
| 9 | osd | 262,144 | `74db6f6aae8485ef79bbb30a56b19482` | expected |
| 10 | upgrade | 131,072 | `8039174560de61bc2874996a22725e04` | probably |

Box 1's dumps plus `xtv125d-data.tar` (factory `/root/data`) and `xtv125d-ui.tar` are the reference set;
keep them on the NAS. Hashing the "expected" rows on each new box confirms whether it runs identical firmware.
**Never write `config`, `nvram` or `cert` from one box to another.**

### What the UI pages show (`/root/titanium/demo_page`, 2026-10-24)

The whole UI is HTML + JavaScript on the Galio browser, talking to the box through an `xsystem` object.

- **Local mode is `kumat/vbrick/home.htm` + `main.js`.** It reads `/root/data/channels.xml` and
  `adjust.xml`. `FullScreen` and `AutoChannelNumbers` must be exactly `1` to count. **`DfltStrm`: any
  non-empty value** marks the default stream; with one stream it defaults to index 0 anyway.
- **`gotourl <URL>` points the browser at any page** (VBrick's own comment:
  `gotourl file:///root/titanium/demo_page/kumat/vbrick/home.htm?CXML=channelSpecial.xml` loads a
  different channels file). With a hex argument it's a remote key instead.
- **Stream loss and recovery (multicast `tvPlayer`):** any player error (2 Connect Failed, 3 Lost
  Signal, 5 End of Stream…) makes it disconnect; a check every **10 s** replays the channel if the
  player is in error. So after a headend restart, expect up to ~10 s before the picture returns.
  This is also why the headend keeps the mux alive with PSI/PCR/null packets during gaps: an
  unbroken stream never trips "Lost Signal".
- **Setup menu = `kumat/setup/setup.js`**, writing `xsystem` properties and then
  `xsystem.sysConfigSave(); xsystem.sysReboot()`. The relevant ones:
  - Start Mode Local ⇔ `browserPortalPage = "file:///root/titanium/demo_page/kumat/vbrick/home.htm"`
    (that's also `config.txt`'s `browser.document.default`, so this box may already be Local).
  - Output: `vidHdOutputFmt` / `vidSdOutputFmt`, values like `720p`, `480i`, `576i`.
  - `sysFirmwareUpgradeURL`, `sysTimeServIPAddr`, `sysTimeZone`, `ip4AddrType`/`ip4Addr`…,
    `ip4IGMPVer`, `sysWatchDogDisabled`/`Timeout`.
  - **`rmtAccessType`**: bit 0x01 = SSH, bit 0x02 = telnet. Turning telnet off is `&= 0xfd`.
  - `browserConfigPassword` (`1234`) and **`browserAdvancedConfigPassword`** (`5678` in `env.cfg`):
    the setup menu accepts either; the advanced one unlocks more pages. The 2011 changelog also mentions
    "a unique super password for each STB".
- **Remote key codes** (`kumat/lib/keycode.txt`; these are browser key codes, not the NEC IR codes
  `gotourl` takes): the NEC-en remote has **HELP = 156**, **Setup = 0x40000026**, OK = 13, arrows 37–40,
  Home = 771, Previous = 769, Next = 768, Display = 0x40000206, A/R = 0x40000207.
- `version history.txt` is the EPG/UI changelog (to V6.2, 2011); `epg.ver` says UI 2.1.4.

## Setup without the remote: `tools/xtv125d/bakacast-setup.htm` (untested)

A page that does what the setup menu does, through the same `xsystem` properties: Start Mode Local,
HD and SD output 480i, no upgrade URL, then save and reboot. It draws a before/after table on the
box's video output. From Windows cmd, in the repo folder:

```
ssh vbrick "cat > /root/data/bakacast-setup.htm" < tools\xtv125d\bakacast-setup.htm
ssh vbrick "gotourl 'file:///root/data/bakacast-setup.htm?dry=1'"
ssh vbrick "gotourl file:///root/data/bakacast-setup.htm"
```

The first `gotourl` (`?dry=1`) only shows the current values. Run the second one only if those look
right; it saves and reboots after 10 s. Back up `/root/data` before and after: comparing the two
`env.cfg` files maps the record ids to settings. If this works, boxes 2–14 need no remote at all.

### Still to look at

- The web UI at `http://<box>/`.
- `kumat/diagnostic` and `kumat/status`: whether they can report what the box is playing, for a
  headend health check.
- Whether `channels.xml` accepts the `<Decode prm="…">` options from `himi.xml`.
