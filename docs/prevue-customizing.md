# Customizing the Prevue software (graphics, branding, keys)

Notes for rebranding the emulated Prevue Guide 9.0.4: swapping the TV Guide Channel logos,
promo cards and banners for your own. For running it, see [prevue.md](prevue.md).

## Getting files off (and back onto) the disk

**amitools** (Python) reads and writes Amiga disk images:

```powershell
pip install amitools
xdftool PREVUE.ADF list                     # every file, with sizes
xdftool PREVUE.ADF unpack prevue_files      # copy the whole disk into a folder
```

To put a modified file back:

```powershell
xdftool PREVUE.ADF delete Logo-TVG.iff      # remove the original (use the real name from `list`)
xdftool PREVUE.ADF write Logo-TVG.iff       # add yours under the same name
```

- **Work on a copy.** Keep a pristine `PREVUE.ADF` somewhere safe.
- **If amitools won't install:** `pip install amitools` sometimes wants a C compiler on Windows.
  **ADF Opus** is a free Windows program that does the same with drag and drop.

## What's on the disk

Pieced together from the community wiki and PrevueCLI's source:

| File | What it is |
|---|---|
| `logo.lst` | Plain-text list of the logo images the box cycles through. That includes the TV Guide Channel logo in the grid's gap. Replace the images, or edit the list to add your own. |
| `Banner.ini` → `TVGBANNR.UV` | The banner. The wiki says it needs a **specific 8-color palette**, so it's stricter than the rest. |
| `BRUSH.INI` | Maps backdrop images ("brushes") to IDs. |
| `gradient.ini` | The grid's color gradients. The `p` key reloads it. |
| `PrevueC.font` | The font, including special characters. |
| `curday.dat` | Cached listings. |
| promo cards (e.g. "sportsview") | Image files on the disk. `xdftool … list` / `unpack` will show which ones. |

## Replacing images

1. **Match the original exactly:** the same pixel dimensions, the same number of colors (bitplanes)
   and the same palette slots. The Amiga's display is set up for the originals, so a bigger image or
   one with more colors can display garbled or crash the software. Check each original's specs in your
   image editor and keep them.
2. **Watch for PowerPacker.** Some files may be compressed with it, a common Amiga format
   (PrevueCLI ships a decoder). If a file won't open as IFF, that's probably why. It needs
   unpacking first, and possibly repacking afterwards.
3. **Test one file at a time.** Write it into a copy of the ADF, boot it in WinUAE, and watch for
   it. The logo shows up within a few minutes, and the promo cards appear several times an hour.

### Updating over the serial line instead (later)

The real boxes were customized remotely, and the satellite data protocol has a **file download**
command that writes files onto the Amiga's disk over the serial line. PrevueCLI uses it to send
logos (`LOGO.LST` + images), brushes (`BRUSH.INI` + images) and the scroll banner, then tells the box
to reload them, with no reboot needed. `prevue_feed.py` doesn't do this yet. If it's added, the ADF
must be writable in WinUAE (floppy write-protect off).

## Documentation

As far as we can find, no official manuals survive; they were internal United Video documents.
The community has reverse-engineered a lot:

- **[Prevue (ESQ) – Prevue Guide Wiki](https://prevueguide.com/wiki/Prevue_(ESQ))**: keyboard
  commands and file notes.
- **Ari Weinstein's Prevue forums** have the deepest material: the
  [Amiga serial commands thread](https://www.ariweinstein.com/prevue/viewtopic.php?t=64) and the
  [Amiga disassembly thread](https://ariweinstein.com/prevue/viewtopic.php?t=140&start=50).
- **[PrevueGuide.neocities.org](https://prevueguide.neocities.org/guides/Esquire/1)**: emulation
  guides, custom text ads and logos.
- **[PrevueCLI source](https://github.com/AriX/PrevueCLI)**: `SendLogos`, `SendBrushes` and
  `SendScrollBanner` show the file names and the upload sequence.

### Keyboard commands (from the wiki)

| Key | Effect |
|---|---|
| `S` | Stop the listings scrolling |
| `s` | Continue scrolling |
| `Ctrl-S` | Single-step the listings |
| `Ctrl-U` | Stop listings after the current block |
| `g` | Graphical ad mode |
| `h` | Show channel (CLU) information |
| `p` | Reload `gradient.ini` |
| Diagnostic mode: `Shift-1`–`Shift-4` | Change the TEXT, VIN, LINE and GRPH settings |
| Diagnostic mode: `1`–`9` | Audio and video control |
