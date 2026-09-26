# Bakacast channel plan

**14 channels:**
- **12 FS42 stations on CATV 2–13;**
- **the WeatherStar channel on 40**, in homage to the WeatherStar 4000;
- **the Prevue Guide on 42**, in homage to FieldStation42.

2–13 fill one Blonder Tongue OC-12D and match the rack of channel 2–13 modulators. 40 and 42
go on a second OC-12D, and the two combiners are merged into the plant.

## The rule: one number everywhere

A channel's number is the same on the TV dial, in `channel_number` in its FS42 station
config, in the headend's `live_channels`, in the Prevue grid, and in its multicast group.
The headend sends channel *N* to `239.42.0.N`, so channel 8 is `239.42.0.8` and Prevue is
`239.42.0.42`. With one number throughout, the Prevue grid never disagrees with the dial,
and each decoder and modulator pair can be labelled with a single number.

## Lineup

| Ch | Visual carrier | Service | Source | Multicast group | Combiner input |
|---:|---:|---|---|---|---|
| 2  | 55.25 MHz  | FS42 station | `channel_number: 2`  | 239.42.0.2  | A1 |
| 3  | 61.25 MHz  | FS42 station | `channel_number: 3`  | 239.42.0.3  | A7 |
| 4  | 67.25 MHz  | FS42 station | `channel_number: 4`  | 239.42.0.4  | A2 |
| 5  | 77.25 MHz  | FS42 station | `channel_number: 5`  | 239.42.0.5  | A8 |
| 6  | 83.25 MHz  | FS42 station | `channel_number: 6`  | 239.42.0.6  | A3 |
| 7  | 175.25 MHz | FS42 station ⚠ | `channel_number: 7`  | 239.42.0.7  | A9 |
| 8  | 181.25 MHz | FS42 station | `channel_number: 8`  | 239.42.0.8  | A4 |
| 9  | 187.25 MHz | FS42 station | `channel_number: 9`  | 239.42.0.9  | A10 |
| 10 | 193.25 MHz | FS42 station ⚠ | `channel_number: 10` | 239.42.0.10 | A5 |
| 11 | 199.25 MHz | FS42 station | `channel_number: 11` | 239.42.0.11 | A11 |
| 12 | 205.25 MHz | FS42 station | `channel_number: 12` | 239.42.0.12 | A6 |
| 13 | 211.25 MHz | FS42 station | `channel_number: 13` | 239.42.0.13 | A12 |
| 40 | 319.25 MHz | **WeatherStar 4000+** | live: `tools/weather/weather_channel.sh` | 239.42.0.40 | B1 |
| 42 | 331.25 MHz | **Prevue Guide** (MICM-45D) | live: `tools/prevue/prevue_channel.sh` | 239.42.0.42 | B3 |

⚠ = check for off-air pickup first (see [Channels 7 and 10](#channels-7-and-10)).

Which FS42 station goes in which slot from 2 to 13 is your call. To swap them, change each
station's `channel_number`; nothing else in the chain cares.

### Why this works

- **2–13 tune in any mode.** On the standard (STD) cable plan, channels 2–13 use the same
  frequencies as broadcast VHF, so a TV finds them whether it's set to Cable or to Antenna/Air.
- **40 and 42 need Cable mode.** They're superband channels (318–336 MHz). Every Bakacast set is
  cable-ready, so that's fine, but a set left on Antenna/Air will skip them.
- **Some sets have a STD / HRC / IRC switch. Leave it on STD.** HRC and IRC shift the
  carriers, and on IRC channels 5 and 6 move by 2 MHz.
- **40 and 42 aren't adjacent.** Channel 41 sits between them, 12 MHz apart, so they don't
  need the adjacent-channel care that 2–13 get.
- **Loss is low.** Coax loss at 55–336 MHz is small, so an apartment run needs no tilt
  compensation. 40 and 42 arrive only a few tenths of a dB below 2–13.
- **Aircraft bands:** the plan skips 108–137 MHz (CATV 98, 99 and 14–16) entirely.
  40 and 42 do sit inside the military aircraft band (225–400 MHz), as most cable channels
  above 23 do. The FCC's leakage rules for cable operators exist because of this band. A small
  closed home system with good compression fittings leaks next to nothing, but it's one more
  reason to fit every connector properly and terminate every unused port.

## Combiners

**Combiner A (OC-12D #1): channels 2–13.** On an OC-12D, neighbouring inputs have 38 dB of
isolation and other pairs have 65 dB, so no two channels next to each other on the dial share
neighbouring inputs. Evens go on 1–6 and odds on 7–12:

```
input:    1   2   3   4   5   6   7   8   9  10  11  12
channel:  2   4   6   8  10  12   3   5   7   9  11  13
```

Neighbouring inputs always hold channels at least two apart (e.g. 2 and 4), and inputs 6 and 7
hold 12 and 3. Before you wire it, check how the unit's own input labels run. If its numbering
isn't a simple 1–12 row, keep the same idea: no dial-neighbours on physically neighbouring
inputs.

**Combiner B (OC-12D #2): channels 40 and 42,** on inputs 1 and 3 (non-neighbouring, for good
measure). **Terminate the other ten inputs** with 75 Ω F terminators. That's the bag of 10 on
the shopping list. The spare inputs leave room for more channels later.

**Merging A and B:** a good 2-way splitter used backwards, with both OC-12D outputs into its two
"out" ports and the plant on its "in" port. Use a 5–1000 MHz, all-port-passing type. It costs
3.5 dB on every channel, which the level budget below already includes. Its 20–25 dB
port-to-port isolation, plus the OC-12Ds' own isolation, keeps the two combiners from feeding
back into each other's modulators.

```
2–13 modulators ──► OC-12D A ──┐
                               ├──► 2-way (reversed) ──► 4-way splitter ──► wall plates
40, 42 modulators ─► OC-12D B ─┘
```

*Cheaper alternative, if you'd rather not buy a second OC-12D:* combine 40 and 42 with a
reversed 2-way splitter, then join them to OC-12D A's output with a directional coupler (a −12 dB
tap). The 2–13 channels lose about 1.5 dB through the coupler's through port instead of 3.5 dB,
and 40 and 42 lose about 15.5 dB (3.5 + 12). Balance the rest with the modulators' output
controls. It's a few dollars of parts, but it leaves no spare inputs.

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
on top of the cable signal. Against a clean +5 dBmV cable carrier the risk is small.

1. **Bare set:** on each CRT, put a 75 Ω terminator on the antenna input and compare the snow on
   7 with 8, and on 10 with 9. (First CRT checked on 2026-09-23: clean.)
2. **Through a drop:** connect the set to a wall plate, with a terminator on the closet end of the
   run, and repeat the comparison.
3. **Once the plant is live:** look for faint diagonal lines or a raised noise floor on 7 and 10
   that the other channels don't have.

**If either slot is bad:** move that FS42 station to a clean channel with a modulator for it, for
example one in 23–39. Renumber it everywhere, including `channel_number` and multicast group
`239.42.0.N`, and put it on combiner B. (The MICM-45D on 42 used to be the spare for this job.
It's now Prevue's modulator.)

## Levels (per channel, rough budget)

| Stage | 2–13 | 40, 42 |
|---|---|---|
| MICM-45D output (+45 dBmV max), turned down to the bottom of its 10 dB range | +35 dBmV | +35 dBmV |
| OC-12D (−18 dB) | +17 | +17 |
| 2-way merge (−3.5 dB) | +13.5 | +13.5 |
| 4-way splitter (−7 dB) | +6.5 | +6.5 |
| ~50 ft RG6 (≈ −1.5 dB at 211 MHz, ≈ −1.8 dB at 331 MHz) | **≈ +5 dBmV** | **≈ +4.7 dBmV** |

That's in the middle of the 0 to +10 dBmV target, with no pads needed. Set every modulator to the
same output, then trim individual rooms (such as the short Bedroom 2 run) with pads if needed.
Take the measurements on the test day.

## Config for this lineup

In `confs/main_config.json`:

```json
"headend": {
  "live_channels": {
    "40": { "name": "WEATHER", "command": "bash tools/weather/weather_channel.sh",
            "env": { "WEATHER_LOCATION": "05443, USA" } },
    "42": { "name": "PREVUE",  "command": "tools/prevue/prevue_channel.sh",       "env": { } }
  }
},
"prevue": {
  "channels": { "40": { "call_letters": "WEATHER", "title": "Local Forecast" },
                "42": { "title": "Prevue Guide" } }
}
```

The `env` blocks are abbreviated. [prevue.md](prevue.md) and [weather.md](weather.md)
have the full settings. The Prevue grid lists the twelve FS42 stations and then 40 and 42,
each live channel with an all-day program. Give the twelve FS42 stations `channel_number` 2–13
in their station configs, then `python3 headend.py --list` should show all 14. That's about
98 Mb/s of multicast, well within gigabit.

## Labelling

Mark each channel number on all four pieces of its chain: the decoder, the composite
patch cable, the modulator and the combiner input cable. That's 14 chains, one number each.
