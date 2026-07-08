# NegativeMaster

NegativeMaster is a film negative conversion toolkit for camera-scanned negatives. It removes the orange mask, inverts the image to a positive, and applies white balance, tone, crop, denoise, sharpening, HSL, curves, and batch export controls.

The repository includes two front ends over the same processing idea:

- `decast.py`: Python CLI and Flask-based local web UI.
- `FilmDecastSwift/`: native macOS SwiftUI app and core engine.

## Features

- Color negative, black-and-white negative, and positive slide modes.
- RAW input through `rawpy` in Python and `CIRAWFilter` in the Swift app.
- Supported RAW extensions include `.ARW`, `.ARQ`, `.CR2`, `.CR3`, `.NEF`, `.RAF`, `.DNG`, `.RW2`, `.ORF`, `.PEF`, `.SRW`, `.3FR`, `.IIQ`, and `.RAW`.
- Standard image input: `.tif`, `.tiff`, `.png`, `.jpg`, `.jpeg`, `.bmp`, `.webp`.
- Density-space orange-mask removal and inversion.
- Crop tools, rotation, mirroring, auto frame detection, auto straighten (deskew), and aspect presets.
- Box-based white balance sampling that averages the selected area to reduce grain/noise error.
- darktable-negadoctor-style guided sampling (optional): box-select the film base (mask removal), a shadow region (black point), and a highlight region (white point) to override the automatic per-channel levels. Falls back to the automatic path when left unset.
- Lightroom-style finishing controls: exposure, highlights, shadows, whites, blacks, curves, HSL, vibrance, vignette, sharpening, and chroma denoise.
- Histogram matching against a reference positive scan.
- 16-bit TIFF and JPEG export, with batch export in the UI.
- Per-image parameter memory, reusable presets, and whole-roll parameter application.

## Install

Python 3.10+ is recommended.

```bash
git clone git@github.com:THEzsc/NegativeMaster.git
cd NegativeMaster
```

The shell launchers create `.venv` and install dependencies on first run:

```bash
./run.sh -h
```

Manual setup is also fine:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
```

## Web UI

```bash
./gui.sh
./gui.sh "/path/to/negatives"
./gui.sh --port 8766
```

Open `http://127.0.0.1:8765` if the browser does not open automatically.

The UI lets you browse a folder, load a negative, adjust the conversion while previewing, save presets, and export a single frame or a checked batch.

Use **box white balance** when a neutral area is noisy or grainy: enable the white-balance picker, drag a rectangle over a neutral gray/white region, and the converter will average the selected area instead of trusting one pixel.

Use **apply current settings to roll** after tuning one frame. If files are checked, only those files receive the current parameters; otherwise the current file list is treated as the roll. Batch export can then use the saved per-file parameters.

## CLI

Convert one RAW negative:

```bash
./run.sh -i input.ARW -o positive.tif --crop 0.08
```

Rotate or mirror before conversion:

```bash
./run.sh -i input.ARW -o positive.tif --crop 0.08 --rotate 180 --flip h
```

Auto-detect the film frame and straighten it (no manual crop needed):

```bash
./run.sh -i input.ARW -o positive.tif --auto-crop --auto-level
```

Batch process a folder (auto frame + straighten each shot):

```bash
./run.sh -i negatives/ -o positives/ --recursive --auto-crop --auto-level
```

Use a reference positive scan for histogram matching:

```bash
./run.sh -i input.ARW -o positive.tif --crop 0.08 --match reference-positive.tif
```

Apply a preset and export JPEG:

```bash
./run.sh -i input.ARW -o positive.jpg --format jpg --quality 92 --preset 柯达暖调
```

See all options:

```bash
./run.sh -h
```

## How It Works

NegativeMaster treats the input as linear RGB transmittance and converts it to density space:

```text
D = -log10(transmittance)
```

For color negatives, the orange mask is modeled as a per-channel additive offset in density space. The converter estimates black and white points per channel, subtracts the mask/base offset, normalizes each channel, then applies the chosen tone and finishing controls.

This makes the core inversion predictable and keeps color correction separate from later creative adjustments.

## Common Options

| Option | Description | Default |
| --- | --- | --- |
| `-i, --input` | Input file or folder | required |
| `-o, --output` | Output file or folder | input path plus suffix |
| `--crop F` | Crop all sides before processing, 0-0.45 | `0` |
| `--crop-rect x0,y0,x1,y1` | Normalized rectangle crop | none |
| `--auto-crop` | Detect and crop the film frame | off |
| `--auto-level` | Detect frame tilt and straighten (best with `--auto-crop`) | off |
| `--level-angle` | Manual free-angle rotation / straighten in degrees; auto-insets to hide corners | `0` |
| `--rotate` | Clockwise rotation: 0, 90, 180, 270 | `0` |
| `--flip` | `none`, `h`, or `v` | `none` |
| `--mode` | `color`, `bw`, or `positive` | `color` |
| `--negadoctor` | Use the darktable-negadoctor film print engine (off by default; color mode) | off |
| `--nd-gamma`, `--nd-exposure` | negadoctor paper grade and brightness gain | `2.4`, `1.0` |
| `--black-pct`, `--white-pct` | Auto black/white point percentiles | `0.5`, `99.7` |
| `--base-rect x,y,w,h` | Use a film-base rectangle for mask anchoring | auto |
| `--wb` | `gray` or `none` | `gray` |
| `--wb-rect x0,y0,x1,y1` | Use the average color in a normalized rectangle for white balance | none |
| `--wb-point x,y` | Legacy point white balance, using a small neighborhood | none |
| `--gamma` | Output gamma; higher brightens midtones | `1.8` |
| `--contrast` | S-curve contrast, -1 to 1 | `0.08` |
| `--saturation` | Saturation multiplier | `1.0` |
| `--denoise R` | Chroma denoise radius in pixels | `0` |
| `--raw-denoise` | Enable RAW FBDD denoise | off |
| `--match PATH` | Match tone/color to a reference image | none |
| `--format` | `tif`, `png`, or `jpg` | `tif` |
| `--bits` | `8` or `16`; 16-bit is TIFF-only | `16` |
| `--resize N` | Resize output long edge to N pixels | `0` |

## Presets

Built-in presets live in `presets/` and are shared by the CLI and web UI:

- 柯达暖调
- 富士青绿
- 人像柔和
- 风光通透
- 黑白经典
- 褪色胶片
- 负冲风格
- 电影青橙

Save new presets with `--save-preset NAME` or through the web UI.

## Native macOS App

The SwiftUI version is in `FilmDecastSwift/` and requires macOS 14+ and Xcode 15+.

```bash
cd FilmDecastSwift
swift build
swift run SmokeTest
swift run FilmDecast
```

For Xcode usage, see `FilmDecastSwift/README_XCODE.md`.

## Repository Layout

```text
.
├── decast.py                 Python CLI and core pipeline
├── gui.py                    Flask web UI
├── run.sh                    CLI launcher with venv bootstrap
├── gui.sh                    Web UI launcher with venv bootstrap
├── requirements.txt          Python dependencies
├── presets/                  Shared tone presets
└── FilmDecastSwift/          Native macOS SwiftUI implementation
```

Runtime state such as `.venv/`, `settings/`, logs, Swift build products, and local sample scans are intentionally ignored.

## Notes

- RAW decoding depends on the underlying decoder. If a camera format is listed but does not open, update `rawpy`/LibRaw or try the macOS app.
- For best color, crop away film borders before automatic tone estimation or use `--base-rect` to sample a clear film-base area.
- The input should be an unreversed negative. Feeding an already-positive image in negative mode will invert it again.

## Contributors

- **THEzsc** (Project Creator & Main Developer)
- **Antigravity (Google DeepMind AI)** (AI Pair Programmer) — Assisted with frontend GUI visual redesign, slider styling, Canvas rendering optimizations (curves and histograms), SVG icon modernization, and SwiftUI build orchestration.
