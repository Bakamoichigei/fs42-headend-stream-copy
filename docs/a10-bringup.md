# A10 headend bring-up: from a bare box to a single-channel test

This takes the A10-7800 box from a blank SSD to one FS42 channel coming out of `headend.py`,
checked from the Windows PC. Nearly every step is copy and paste. Everything after
step 1 runs over SSH.

The hardware steps (board swap, BIOS update, 45 W cTDP) are on the punch list. Finish them
first. Keep the box at **45 W cTDP**, because the 80 W PSU's 12 V rail is the limit.

## 0. Before Linux

- **BIOS:** update it, set cTDP to 45 W, and turn on "Restore on AC power loss", so the headend comes back after a power cut.
- **Memory:** run one full pass of Memtest86+ (it's on the Debian installer's boot menu, or on its own USB stick). A board that's been in a drawer deserves one.
- **Network:** give the box a DHCP reservation on your router, so its address never changes. This doc calls it `headend`, and uses `<headend-ip>` for the address and `<pc-ip>` for the Windows PC's.

## 1. Install Debian 13 (on the box, with a keyboard and monitor)

Use the amd64 netinst stick.
- **Hostname:** `headend`.
- **User:** create yourself as the normal user and set a root password.
- **Software selection:** untick the desktop and tick only **SSH server** and **standard system utilities**.

After the first boot, note the IP address (`ip -br a`). From here on, work from the Windows PC:

```powershell
ssh <you>@<headend-ip>
```

## 2. Packages

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git python3 python3-venv python3-pip python3-dev build-essential \
                    ffmpeg mpv tmux htop curl lm-sensors
```

(`build-essential` and `python3-dev` are there for FS42's Python modules that compile, such as `evdev`.)

**Check the CPU limit held:** run `sensors` and then `htop`. Under load later, the CPU package
should stay around 45 W and nothing should reset.

## 3. Get the code

```bash
cd ~
git clone https://github.com/Bakamoichigei/fs42-headend-stream-copy.git fs42
cd fs42
git config core.fileMode false        # Windows commits lose the +x bits; don't let that dirty the tree
chmod +x prevue_feed.py tools/prevue_serial_bridge.py tools/prevue/prevue_channel.sh \
         tools/headend_prep.sh tools/weather/weather_channel.sh
```

This clone is read-only: you pull updates here and push from GitHub Desktop as usual.
To update later, run `cd ~/fs42 && git pull`.

*Optional permanent fix for the +x bits:* in GitHub Desktop, choose **Repository → Open in
Command Prompt** and run
`git update-index --chmod=+x prevue_feed.py tools/prevue_serial_bridge.py tools/prevue/prevue_channel.sh tools/headend_prep.sh tools/weather/weather_channel.sh`,
then commit and push. This needs Git for Windows on the PATH.

## 4. Install FS42

```bash
cd ~/fs42
bash install.sh                  # press Enter; it makes the env/ virtualenv and the runtime/ and catalog/ folders
source env/bin/activate          # do this in every new SSH session before running FS42 tools
```

The installer carries on past modules that fail to install and lists them at the end. The
GUI modules (PySide6, glfw, PyOpenGL) don't matter on a headless headend. **`ffmpeg-python`
does matter**, because the live channels need it. If it's in the failed list, run `pip install ffmpeg-python`.

## 5. Test media in the house format

Copy a few videos from the PC. Three or four episodes of anything is enough, ideally 22–45
minutes each. Windows has `scp` built in:

```powershell
ssh <you>@<headend-ip> "mkdir -p ~/incoming"
scp "D:\path\to\test videos\*" <you>@<headend-ip>:~/incoming/
```

Then, on the headend:

```bash
cd ~/fs42
bash tools/headend_prep.sh --slate runtime/slate.ts            # the filler the headend shows for gaps
JOBS=4 bash tools/headend_prep.sh --dir ~/incoming catalog/test/shows
ls -lh catalog/test/shows
```

`--dir` mirrors the folder into house-format `.ts` files: MPEG-2 720×480i, 4:3, 7 Mb/s, MP2
audio. It's a real transcode, so it takes a while. Timing it is your first A10 benchmark.
(In production this job runs on the capture rig instead.)

## 6. A test station

Create `confs/test.json`. It runs one channel, on 24 hours a day, with no commercials:

```json
{"station_conf": {
  "network_name": "TEST",
  "channel_number": 2,
  "network_type": "standard",
  "content_dir": "catalog/test",
  "commercial_free": true,
  "fallback_tag": "shows",
  "day_templates": { "allday": {
      "0": "shows",  "1": "shows",  "2": "shows",  "3": "shows",  "4": "shows",  "5": "shows",
      "6": "shows",  "7": "shows",  "8": "shows",  "9": "shows",  "10": "shows", "11": "shows",
      "12": "shows", "13": "shows", "14": "shows", "15": "shows", "16": "shows", "17": "shows",
      "18": "shows", "19": "shows", "20": "shows", "21": "shows", "22": "shows", "23": "shows" } },
  "monday": "allday", "tuesday": "allday", "wednesday": "allday", "thursday": "allday",
  "friday": "allday", "saturday": "allday", "sunday": "allday"
}}
```

Then build the catalog and a week of schedule:

```bash
python3 station_42.py -r TEST        # catalog the files
python3 station_42.py -w TEST        # add a week of schedule
python3 station_42.py -e             # summary: TEST should show a schedule
```

## 7. Headend config for the test

For this test, send the channel as **unicast straight to the Windows PC** rather than multicast.
Without an IGMP-snooping switch, multicast floods every port and Wi-Fi access point on the
home network, and 7 Mb/s of that can choke Wi-Fi. Unicast goes to one machine only.

Create `confs/main_config.json`, or add the `headend` block if the file already exists:

```json
{
  "headend": {
    "interface": "<headend-ip>",
    "slate_file": "runtime/slate.ts",
    "channels": { "2": { "url": "udp://<pc-ip>:5000" } }
  }
}
```

## 8. Run the tests

```bash
cd ~/fs42 && source env/bin/activate

python3 headend.py --list                          # TEST on channel 2 -> udp://<pc-ip>:5000
python3 headend.py --check                         # every file due in the next 24 h matches the house format

# render 10 minutes faster than real time, and time it: the A10's splicing speed
time python3 headend.py -c 2 --record /tmp/rec --fast --duration 600
ffprobe -v error -show_entries stream=codec_name,width,height,field_order -of compact /tmp/rec/ch02.ts
```

**Live, in real time:** run it in `tmux` so it survives an SSH disconnect.

```bash
tmux new -s headend
python3 headend.py -c 2              # Ctrl-C to stop; detach with Ctrl-B then D
```

On the **Windows PC**:
- **VLC:** Media → Open Network Stream → `udp://@:5000`. Allow VLC through the Windows firewall
  when it asks. You should see the channel, with a clean cut at each file change.
- **Checking the stream:** `ffprobe -i udp://0.0.0.0:5000` shows the programme (MPEG-2 video
  720×480 plus MP2 audio). Tools → Media Information → Statistics in VLC should show about 7 Mb/s
  input, with no lost or discarded packets growing.
- **On the headend:** `htop` should show the channel worker at a few percent of one core.
  `cat runtime/headend/ch02.json` shows what's airing, the splice count and any errors.

**Pass:** it plays through at least one file change with no glitch, CPU stays low, and `ch02.json`
shows no errors.

## 9. Optional: picture on a CRT before the XTV125D arrives

Play the stream full-screen on the Windows PC. VLC with deinterlacing off is fine for this.
Then take the PC's HDMI through a cheap HDMI-to-composite converter into the MICM-45D, and tune the
TV to channel 42 through 20–30 dB of pads. It proves the whole chain end to end. The converter's
picture says nothing about final quality: that's the XTV125D's job.

## Next

- **Run it as a service**, once you're happy with the test:
  ```bash
  bash install/install_services.sh            # answer n to all four prompts: those are for a TV-playout box, not a headend
  systemctl --user enable --now fs42-headend  # the installer copies this unit but doesn't prompt for it
  sudo loginctl enable-linger $USER           # keep user services running with nobody logged in, and start them at boot
  journalctl --user -u fs42-headend -f        # its log
  ```
- **Weather:** the live channel, with install steps in [weather.md](weather.md).
- **Prevue:** the live channel, in [prevue.md](prevue.md) (FS-UAE genlock is still to verify).
- **Load test:** add stations toward the full 14 and watch `htop` and the temperatures, as on the punch list.
