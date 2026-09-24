# Bakacast channel plan

Twelve channels on **CATV 2–13**: the Prevue Guide, the WeatherStar weather channel, and ten
FS42 stations. That fills the Blonder Tongue OC-12D's 12 inputs exactly, and it matches
the rack of channel 2–13 modulators.

## The rule: one number everywhere

A channel's number is the same on the TV dial, in `channel_number` in its FS42 station
config, in the headend's `live_channels`, in the Prevue grid, and in its multicast group.
The headend sends channel *N* to `239.42.0.N`, so channel 8 is `239.42.0.8`. With one
number throughout, the Prevue grid never disagrees with the dial, and each decoder and
modulator pair can be labelled with a single number.

## Lineup

| Ch | Visual carrier | Service | Source | Multicast group | OC-12D input |
|---:|---:|---|---|---|---:|
| 2  | 55.25 MHz  | **Prevue Guide** | live: `tools/prevue/prevue_channel.sh` | 239.42.0.2  | 1 |
| 3  | 61.25 MHz  | FS42 station | `channel_number: 3`  | 239.42.0.3  | 7 |
| 4  | 67.25 MHz  | FS42 station | `channel_number: 4`  | 239.42.0.4  | 2 |
| 5  | 77.25 MHz  | FS42 station | `channel_number: 5`  | 239.42.0.5  | 8 |
| 6  | 83.25 MHz  | FS42 station | `channel_number: 6`  | 239.42.0.6  | 3 |
| 7  | 175.25 MHz | FS42 station ⚠ | `channel_number: 7`  | 239.42.0.7  | 9 |
| 8  | 181.25 MHz | FS42 station | `channel_number: 8`  | 239.42.0.8  | 4 |
| 9  | 187.25 MHz | FS42 station | `channel_number: 9`  | 239.42.0.9  | 10 |
| 10 | 193.25 MHz | FS42 station ⚠ | `channel_number: 10` | 239.42.0.10 | 5 |
| 11 | 199.25 MHz | FS42 station | `channel_number: 11` | 239.42.0.11 | 11 |
| 12 | 205.25 MHz | FS42 station | `channel_number: 12` | 239.42.0.12 | 6 |
| 13 | 211.25 MHz | **WeatherStar 4000+** | live: `tools/weather/weather_channel.sh` | 239.42.0.13 | 12 |

⚠ = check for off-air pickup first (see [Channels 7 and 10](#channels-7-and-10)).

Prevue and the weather channel bookend the dial, which leaves 3–12 as one unbroken block
for the FS42 stations. Which station goes in which slot is your call. To swap them, change
each station's `channel_number`; nothing else in the chain cares.

### Why 2–13 works well

- **Any tuner mode works.** On the standard (STD) cable plan, channels 2–13 use the same
  frequencies as broadcast VHF. A TV finds all twelve whether it's set to Cable or to
  Antenna/Air, and autoprogram works either way.
- **Some sets have a STD / HRC / IRC switch. Leave it on STD.** HRC and IRC shift the
  carriers, and on IRC channels 5 and 6 move by 2 MHz.
- **Loss is low.** Coax loss at 55–211 MHz is small, so an apartment run needs no tilt
  compensation. All twelve channels arrive at nearly the same level.
- The plan stays out of the FM band (88–108 MHz) and the aircraft band (108–137 MHz),
  which CATV 95–99 and 14–16 would sit in.

## Combiner inputs

On the OC-12D, neighbouring inputs have 38 dB of isolation and other pairs have 65 dB. So no
two channels next to each other on the dial share neighbouring inputs. Evens go on 1–6 and
odds on 7–12:

```
input:    1   2   3   4   5   6   7   8   9  10  11  12
channel:  2   4   6   8  10  12   3   5   7   9  11  13
```

Neighbouring inputs always hold channels at least two apart (e.g. 2 and 4), and inputs 6 and 7
hold 12 and 3. Before you wire it, check how the unit's own input labels run. If its numbering
isn't a simple 1–12 row, keep the same idea: no dial-neighbours on physically neighbouring
inputs.

## Adjacent-channel operation

Channels 2-3-4, 5-6 and 7 through 13 are adjacent on the dial, which is normal for cable.
It stays clean as long as:

- **The visual carriers are within about 2 dB of each other.** A strong channel next to a
  weak one shows up as a faint beat or ghost on the weak one.
- **The aural carrier is about 15 dB below visual.** The MICM-45D adjusts from −11 to −19 dB.
  If it's too hot, it buzzes into the next channel up.
- **The modulators are SAW-filtered.** The MICM-45D is, with −66 dBc spurious output.
  Check the model on the rack's listing: some older non-SAW units splatter into the
  neighbouring channel.

## Channels 7 and 10

Two local digital (ATSC) stations transmit on these frequencies, both roughly 30 miles from 05443:

| Freq | Station | Transmitter |
|---|---|---|
| 7  (174–180 MHz) | WVNY (ABC 22), RF 7 | Mount Mansfield |
| 10 (192–198 MHz) | WVER (Vermont Public), RF 10 | Grandpa's Knob |

A CRT with poor shielding can pick an off-air signal up directly, straight through the chassis,
on top of the cable signal. Against a clean +5 dBmV cable carrier the risk is small, but it's
worth a five-minute check before you commit to those two slots:

1. On each CRT, put a 75 Ω terminator on the antenna input (no cable) and tune to 7, then 8.
   Then do the same with 10 and 9.
2. Look at the snow. If 7 or 10 look the same as their neighbours, there's no pickup. If the snow
   is visibly grainier, brighter or patterned, the set is picking the station up.
3. Once the plant is live, also look for faint diagonal lines or a raised noise floor on 7 and 10
   that the other channels don't have.

**If either slot is bad,** the MICM-45D on **channel 42** (331.25 MHz) is the spare. Swap it
onto that input and renumber that station to 42 everywhere, including `channel_number` and
multicast group `239.42.0.42`. The TVs then need Cable mode to tune it. There are no local
broadcast stations near 331 MHz.

## Levels (per channel, rough budget)

| Stage | Level |
|---|---|
| MICM-45D output (+45 dBmV max), turned down to the bottom of its 10 dB range | +35 dBmV |
| OC-12D (−18 dB) | +17 dBmV |
| 4-way splitter (−7 dB) | +10 dBmV |
| ~50 ft RG6 at 211 MHz (≈ −1.5 dB) | ≈ +8.5 dBmV at the wall plate |

That's already inside the 0 to +10 dBmV target. Set every modulator to the same output, then
pad the combiner output (or individual rooms, such as the short Bedroom 2 run) to land each
plate in the target. Take the measurements on the test day.

## Config for this lineup

In `confs/main_config.json`:

```json
"headend": {
  "live_channels": {
    "2":  { "name": "PREVUE",  "command": "tools/prevue/prevue_channel.sh",       "env": { } },
    "13": { "name": "WEATHER", "command": "bash tools/weather/weather_channel.sh",
            "env": { "WEATHER_LOCATION": "05443, USA" } }
  }
},
"prevue": {
  "channels": { "2":  { "title": "Prevue Guide" },
                "13": { "call_letters": "WEATHER", "title": "Local Forecast" } }
}
```

The `env` blocks are abbreviated. [prevue.md](prevue.md) and [weather.md](weather.md)
have the full settings. The Prevue grid lists both live channels, each with an all-day
program, next to the FS42 stations. Give the ten FS42 stations `channel_number` 3–12 in
their station configs, then `python3 headend.py --list` should show all twelve on
`239.42.0.2`–`.13`.

## Labelling

Mark each channel number on all four pieces of its chain: the decoder, the composite
patch cable, the modulator and the combiner input cable. Twelve labels, one number each.
