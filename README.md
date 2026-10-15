# NegativeMaster

NegativeMaster is a film negative conversion toolkit for camera-scanned negatives. It removes the orange mask, inverts the image to a positive, and applies white balance, tone, crop, denoise, sharpening, HSL, curves, and batch export controls.

The repository includes two front ends over the same processing idea:

- `decast.py` / `gui.py`: Python CLI and Flask-based local web UI for Windows, macOS and Linux.
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
- Local SQLite film archive: roll dates/locations, camera/lens, ISO/EI, development notes, physical storage, tags, frame ratings, sourced covers, and portable metadata/preview backups.

## Install

Use **64-bit Python 3.12 or later; Python 3.13 is recommended**. The pinned NumPy,
imagecodecs and tifffile releases require Python 3.12+. The Python app provides all
conversion and contact-sheet features on Windows; the separate SwiftUI app is macOS-only.

```bash
git clone https://github.com/THEzsc/NegativeMaster.git
cd NegativeMaster
```

The HTTPS clone does not need an SSH key. To contribute or push branches, sign in
to GitHub separately with your preferred Git credential manager.

### Windows 10 / 11

Install [Python 3.13 for Windows](https://www.python.org/downloads/windows/) (64-bit)
with the Python launcher / PATH option enabled. Open the repository in a writable
folder. Double-click **gui.cmd**, or run these from PowerShell / Command Prompt:

```powershell
.\gui.cmd
.\gui.cmd "D:\胶片扫描\旅行 01"
.\gui.cmd --port 8766
.\run.cmd --help
.\run.cmd -i "D:\胶片扫描\底片.ARW" -o "D:\成片\" --auto-crop --auto-level
```

PowerShell scripts are also supplied (`.\gui.ps1` and `.\run.ps1`). If the local
execution policy blocks `.ps1` files, use the `.cmd` launchers: their policy setting
applies only to the launched PowerShell process and does not change system policy.
No administrator privileges are needed. Paths with spaces, Chinese characters,
drive letters and accessible UNC shares are supported. File/folder/export pickers
use Windows native dialogs. The browser opens the requested port automatically.

### macOS / Linux

The shell launchers create `.venv` and install dependencies on first run:

```bash
./run.sh -h
```

Linux's native picker requires a graphical desktop and `python3-tk`; a full path
can always be entered in the app. macOS uses its native AppleScript picker.
All launchers recheck the pinned dependencies, recover an interrupted first install,
and install updates when `requirements.txt` changes. Successful subsequent launches
do not need network access. Python is not installed automatically.

Manual setup is also fine:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
```

For manual Windows setup, use `py -3.13 -m venv .venv`, then replace
`./.venv/bin/python` with `.\.venv\Scripts\python.exe` in the commands above.

## Web UI

```bash
./gui.sh
./gui.sh "/path/to/negatives"
./gui.sh --port 8766
./gui.sh --no-browser
```

Open `http://127.0.0.1:8765` if the browser does not open automatically.

Keep the launcher terminal open; **Ctrl+C** stops the local server. The server only
listens on `127.0.0.1`. For background use, `gui.cmd --daemon --no-browser` (Windows)
or `./gui.sh --daemon --no-browser` (macOS/Linux) prints the process ID and writes
`gui.log` in the repository. Stop that process with `Stop-Process -Id <PID>` in
PowerShell or `kill <PID>` on macOS/Linux. An occupied port is reported; choose
another with `--port`. A mistyped source folder is reported rather than replaced
silently with a default folder.

The UI lets you browse a folder, load a negative, adjust the conversion while previewing, save presets, and export a single frame or a checked batch.

**胶片档案**位于顶部导航（`/archive`）。按卷记录拍摄、冲洗和底片存放信息，关联本地成片，上传胶卷盒或照片封面，并搜索、筛选与备份档案。原始照片不会修改；ZIP 备份包含资料、封面与预览，不含原片。默认数据位于已忽略的 `archive_data/`，可用 `NEGATIVEMASTER_ARCHIVE_DIR` 指定长期存储目录。迁移、封面来源及功能边界见[胶片档案使用说明](data/ARCHIVE_GUIDE.md)。

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

On Windows: `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`.
The GitHub Actions matrix runs Python 3.12 and 3.13 on Windows, macOS and Linux;
native desktop picker interactions still require manual desktop verification.

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
Frontend ordering, crop, local path and asynchronous workflow regressions can be run
with `node --test tests/test_local_paths.cjs tests/test_sheet_model.cjs tests/test_sheet_workflow.cjs`
(Node.js 22+) in addition to the Python suite above. Node.js is only needed for tests.

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
├── gui.cmd / gui.ps1         Windows web UI launchers
├── run.cmd / run.ps1         Windows CLI launchers
├── launcher.py              Shared dependency checks and environment bootstrap
├── platform_support.py      Native pickers, browser opening and background server
├── requirements.txt          Python dependencies
├── presets/                  Shared tone presets
└── FilmDecastSwift/          Native macOS SwiftUI implementation
```

Runtime state such as `.venv/`, `settings/`, logs, Swift build products, and local sample scans are intentionally ignored.

## Notes

- RAW decoding depends on the underlying decoder. If a camera format is listed but does not open, update `rawpy`/LibRaw or try the macOS app.
- For best color, crop away film borders before automatic tone estimation or use `--base-rect` to sample a clear film-base area.
- The input should be an unreversed negative. Feeding an already-positive image in negative mode will invert it again.
- If a Windows Chinese header lacks glyphs, install the Microsoft YaHei / Chinese
  language fonts through Windows Settings. The renderer reads system fonts and
  does not copy or redistribute them. The app also tries Microsoft JhengHei and SimSun.
- If an older checkout already has a Python 3.10/3.11 `.venv`, rename that folder
  and rerun a launcher with Python 3.12+. Keep `settings/`, your photos, XML sidecars
  and exported files; they are independent of the virtual environment.

## Contributors

- **THEzsc** (Project Creator & Main Developer)
- **Antigravity (Google DeepMind AI)** (AI Pair Programmer) — Assisted with frontend GUI visual redesign, slider styling, Canvas rendering optimizations (curves and histograms), SVG icon modernization, and SwiftUI build orchestration.

### 边字与片头

- 边字包含 Citaro Voor 常规／双高度（Jeffrey Visser，CC BY-SA 3.0）、RVP 厚笔曝光字、Phoenix 方形连印、Kodak 粗实印字、CineStill 细等宽字，以及自绘曝光圆点／窄条连印，以及原有点阵、Barlow 窄体和 IBM Plex 等宽字。字体样张由导出渲染器生成；自绘字是风格模拟，不是厂家字体。
- RVP 风格使用自绘的斜切转角、连续笔画与斜杠 0，支持英文字母、数字和常用边字标点。帧号旁可添加向左或向右的实心阶梯箭头，跟随边字颜色、大小和不透明度；默认不显示，不占用片头编号。字体和箭头同时显示在样张与导出中。
- 边字红色光晕独立可调，模拟外侧红晕与亮芯，默认关闭；样张和导出共用渲染。字形参考及证据边界见 [胶片资料](data/FILM_SOURCES.md)。
- 齿孔提供标准圆角、电影弧边（BH 参考）和小圆角方孔，孔沿提供自然切口、琥珀细边和银灰细边。所有孔形保留真实透明开口，并与投影、内缘层次复用同一轮廓。
- 片头按画格加入照片之前。自动模式使用最少的正数格数补齐末行；照片本来满行时增加一行片头。手动模式可指定 0–24 格，保留末行实际长度。片头不消耗照片帧号或逐张裁剪索引。
- 片头有暗片、透明片基，以及暖色漏光、曝光灼白、上下柔光放射、玫瑰光雾、上下不规则烧边、橙红光带。漏光使用连续胶片坐标，左强右弱、跨画格和跨行不重置；可调强度、柔和度并换纹理。默认只影响片头，可主动延伸到前 0–12 张照片；无片头时也可对前几张应用。效果只作用于排版输出，不修改原照片。种子随草稿、版式及项目包保存。
- 顶栏采用更饱满的中等字重信息字，按实际字段长度分配宽度；可显示胶卷型号与 ISO、调整信息字号。所有新设置随草稿、版式与项目保存。

竖构图照片默认顺时针旋转 90° 横放于胶片窗口。单张手动旋转（含 0°）优先；重置构图恢复默认横放。预览、导出和项目恢复遵循相同规则，原照片不改动。

### 背景、层次与配色

- 模糊照片、纯色和渐变背景均可调不透明度，照片和顶栏保持清晰。PNG 保留透明度，JPEG 合成白底。
- 胶片条提供柔和投影、浅色细边、细边加投影、纸白衬边四种分离效果及强度调节，适合在浓重背景上突出片条轮廓。效果默认沿外轮廓和齿孔内缘绘制，可单独关闭齿孔效果。投影可选黑色或白色；宽衬边会收窄齿孔内的描边，保留开口。
- 颜色控件直接展示命名推荐色，背景附带四组渐变搭配；自定义颜色支持三位或六位十六进制色值。选择色卡或搭配可撤销，所有设置随草稿、版式与项目保存。
