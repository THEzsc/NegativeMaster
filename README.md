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

**自动裁剪＋校平** solves crop and leveling together from the original frame
boundaries, preserving your 90° orientation and mirror choices. A fine 0.05°
search near level improves thin-edge detection. Original sensor bounds are
included when calculating the crop, so rotation does not leave black corners.
Repeated clicks calculate an absolute angle rather than accumulating rotations.

**同卷参考** (enabled by default, optional) reads nearby saved XML adjustments
in the same folder when an edge is too weak to detect. At least five consistent
references are required; the current frame and its RAW/JPEG twin are excluded.
Tight creative crops and inconsistent references are rejected. The UI explicitly
reports reference use. These are geometric hints from your edits, not a trained
image model. Disable this option if camera position/film framing changes within
one folder. Reference files and original photos are never modified by detection.
Without reliable detection or references, the current crop/angle are preserved.

Run geometry and API regression tests with:

```bash
./.venv/bin/python -m unittest discover -s tests -v
```

Use **apply current settings to roll** after tuning one frame. If files are checked, only those files receive the current parameters; otherwise the current file list is treated as the roll. Batch export can then use the saved per-file parameters.

## Roll contact sheets

Open **整卷排版** in the shared header, or visit `http://127.0.0.1:8765/sheet`.
Folder imports prefer exported positive files, then use each frame's saved XML or
settings. A RAW file without saved adjustments is skipped with an explanation.
Photo imports can also use ordinary positive images directly. This preparation
does not overwrite the original photos or adjustment sidecars.

The editor supports frame selection and reordering, individual rotation and crop
position, configurable perforated strips and a curved leader, editable numbering
and edge text, blurred-photo/solid/gradient/transparent backgrounds, custom
background images, and an optional white film-information header. Export PNG or
JPEG at widths from 1200 to 10000 pixels, within an 80-megapixel canvas limit.
Export uses the same renderer as the preview and writes sRGB with 300-DPI metadata.
The default destination is a new file in the roll's `整卷展示` subfolder.

Click a photograph or choose **单张** to inspect its composition at a useful size.
The **照片** pane provides 90° rotation, per-frame fit, zoom and crop centers;
when the image is cropped, drag directly on the canvas. Optional thirds guides
are preview-only. **重置当前构图** restores geometry while retaining the frame label.
A drag is one undo step; Alt + Up/Down reorders a focused photo without losing
keyboard focus. Rechecking a photo keeps its position in the displayed sequence.
The canvas toolbar shows tools for the current view, and the photo rail can be
collapsed for more canvas space. On narrow screens it opens as a keyboard-accessible
drawer with a backdrop and Escape dismissal.

The browser draft restores the full ordering, selection (including no selection),
active frame, frame edits and background reference by file path. Missing sources
produce an explicit error and preserve the previous draft. Restore the source
files or load a portable project to resume. The last export path and a repeat-download link remain visible for the current page session.

Preview requests coalesce during continuous edits. A 64 MiB bounded pixel cache
reuses decoded preview images; full-resolution export retains its original path.
On the local 36-photo FOMAPAN roll, median warm backend preview time decreased
from 0.815 s to 0.162 s (about 5×); the first preview remained around 0.80 s.
This measures server rendering requests, excluding browser drawing and debounce.
Frontend ordering, crop and asynchronous workflow regressions can be run with
`node --test tests/test_sheet_*.cjs` in addition to the Python suite above.

**保存项目** creates a portable ZIP containing the prepared positive photos,
custom background and editable layout, so a project remains usable without its
original source folder. Layout presets are stored locally in the browser.

The stock library contains 100 models. Manufacturer documents substantiate 27
edge inscriptions; the remaining inscriptions, fonts and colors are clearly
marked as editable reconstructions. References and limits are recorded in
[data/FILM_SOURCES.md](data/FILM_SOURCES.md). The workbench has day and night modes
with an orange, charcoal and angular visual system.

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

### 边字与片头

- 边字包含 Citaro Voor 常规／双高度（Jeffrey Visser，CC BY-SA 3.0）、自绘曝光圆点／窄条连印，以及原有点阵、Barlow 窄体和 IBM Plex 等宽字。字体样张由导出渲染器生成；自绘字是风格模拟，不是厂家字体。
- 片头按画格加入照片之前。自动模式使用最少的正数格数补齐末行；照片本来满行时增加一行片头。手动模式可指定 0–24 格，保留末行实际长度。片头不消耗照片帧号或逐张裁剪索引。
- 片头有暗片、透明片基、暖色漏光、曝光灼白，可调曝光强度，并选弧形裁切或完整直边。漏光仅渲染新增片头格，使用确定性曝光场。
- 顶栏采用更饱满的中等字重信息字，按实际字段长度分配宽度；可显示胶卷型号与 ISO、调整信息字号。所有新设置随草稿、版式与项目保存。
