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
  <Stream>
    <ProgramName>BAKACAST 7</ProgramName>
    <Message>tv://239.42.0.7:5000</Message>
    <URL>tv://239.42.0.7:5000</URL>
  </Stream>
</STBLocalUI>
```

- `tv://group:port` is the manual's form for an MPEG-2 transport stream multicast.
- `FullScreen` `1` is Local Fullscreen Mode. `0` would be Local Mode, which shows the box's own channel guide.
- Keep the headend on `"encapsulation": "udp"` (the default). The manual's `tv://` examples are raw UDP.
- **`DfltStrm`:** the manual also lists this element, for the stream that plays at power-on.
  The exact form it takes isn't in the parts of the manual we could get at. With only one
  stream in the file, the box should just play that one. If it doesn't, look at the sample
  file the box ships with (step 3 shows how), copy its `DfltStrm` line, and note the answer here.

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
