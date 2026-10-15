---
name: NegativeMaster
description: A local photographic workbench with orange actions and angular mounting geometry.
colors:
  bg: "#111214"
  panel: "#1b1d20"
  surface: "#242629"
  line: "#383b3f"
  fg: "#f2f0ec"
  mut: "#b4b2ad"
  acc: "#ff8b32"
  orange: "#ec6c22"
  stage: "#16181a"
  field: "#151719"
  light-bg: "#edebe6"
  light-panel: "#f8f6f1"
  light-surface: "#e5e2dc"
  light-line: "#c8c3ba"
  light-fg: "#202122"
  light-mut: "#625e57"
  light-acc: "#9b3d00"
  light-orange: "#ed762a"
  light-stage: "#dedbd5"
  light-field: "#fffdfa"
  action-ink: "#161310"
  action-hover: "#ff9949"
typography:
  brand:
    fontFamily: "Barlow Condensed, sans-serif"
    fontSize: "24px"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: ".015em"
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'PingFang SC', 'Segoe UI', sans-serif"
    fontSize: "17px"
    fontWeight: 500
    lineHeight: 1.5
  section:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'PingFang SC', 'Segoe UI', sans-serif"
    fontSize: "14px"
    fontWeight: 600
    lineHeight: 1.5
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'PingFang SC', 'Segoe UI', sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'PingFang SC', 'Segoe UI', sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
  value:
    fontFamily: "IBM Plex Mono, monospace"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  square: "0"
spacing:
  tight: "4px"
  compact: "8px"
  control: "12px"
  group: "16px"
  panel: "20px"
  generous: "24px"
components:
  button-primary:
    backgroundColor: "{colors.orange}"
    textColor: "{colors.action-ink}"
    rounded: "{rounded.square}"
    padding: "10px 19px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.action-hover}"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.fg}"
    rounded: "{rounded.square}"
    padding: "8px 11px"
    height: "36px"
  button-quiet-hover:
    backgroundColor: "{colors.surface}"
  button-icon:
    backgroundColor: "transparent"
    textColor: "{colors.fg}"
    rounded: "{rounded.square}"
    size: "36px"
  input-text:
    backgroundColor: "{colors.field}"
    textColor: "{colors.fg}"
    rounded: "{rounded.square}"
    padding: "8px 10px"
    height: "40px"
  mode-selector:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.fg}"
    rounded: "{rounded.square}"
    padding: "5px 12px"
  mode-selector-selected:
    backgroundColor: "{colors.orange}"
  navigation-item:
    textColor: "{colors.mut}"
    typography: "{typography.body}"
    padding: "10px 18px"
  navigation-item-current:
    textColor: "{colors.fg}"
  inspector-tab:
    textColor: "{colors.mut}"
    typography: "{typography.label}"
    padding: "15px 0"
  inspector-tab-selected:
    textColor: "{colors.acc}"
  inspector-section:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.fg}"
    rounded: "{rounded.square}"
    padding: "24px 22px"
  frame-row:
    textColor: "{colors.fg}"
    rounded: "{rounded.square}"
    padding: "11px 6px"
  frame-row-active:
    backgroundColor: "{colors.surface}"
---

# Design System: NegativeMaster

## Overview

**Creative North Star: "The Photographic Mounting Workbench"**

NegativeMaster is a local photographic workbench. Its visual identity comes from photographic mounting marks: a continuous image area, square control surfaces, fine orthogonal lines and occasional oblique action edges. The orange/charcoal palette, day mode and connected-node icon language are confirmed user commitments.

The chrome stays dense and quiet so photographs and rendered contact sheets carry the visual content. Night mode uses charcoal layers; day mode uses warm paper and dark ink with a deeper orange for readable text. Q Graph's content-first hierarchy and node grammar inform the shell without importing unrelated page compositions.

**Key Characteristics:**
- Continuous image area before controls
- Orange actions and selected states
- Warm day mode and charcoal night mode
- Square controls with occasional cut action corners
- Fine SVG linework with connected nodes

This record describes the shipped shared UI. Its normative source is `static/workbench.css`, loaded after the inherited processing styles in `gui.py`, together with `templates/shell_header.html`, `templates/sheet.html` and the composition interaction in `static/sheet_frame.js`. The direction provenance remains in `.impeccable/surfaces/workbench.md`: the installed launcher emitted `b88fc49d`; the user's pinned identity governs the build. This document neither invents a replacement seed nor makes page strategy into a global token.

## Colors

The palette separates warm orange actions from neutral photographic surroundings. The frontmatter carries the exact source values; `light-*` primitives replace the corresponding night roles under `data-theme="light"`.

### Primary

- **Signal Orange** (`orange`, `light-orange`): filled export/open actions, selected processing modes, checkbox accents and active underlines.
- **Reading Orange** (`acc`, `light-acc`): numeric readouts, links, brand mark, caret and keyboard focus. The day variant is a dark burnt orange rather than the action fill.
- **Action Hover** (`action-hover`): the shared filled action's hover state. **Action Ink** (`action-ink`) is the dark text on that fill.

### Neutral

- **Workbench Ground** (`bg`, `light-bg`): page background.
- **Control Panel** (`panel`, `light-panel`): header, frame rail, inspector and toolbars.
- **Selection Surface** (`surface`, `light-surface`): active rows and neutral control hover backgrounds.
- **Photographic Stage** (`stage`, `light-stage`): the continuous image or sheet canvas.
- **Field Ground** (`field`, `light-field`): editable text and file-list surfaces.
- **Fine Divider** (`line`, `light-line`): borders, section rules and inactive tracks.
- **Main Ink** (`fg`, `light-fg`): controls, section titles, file names and readable content.
- **Supporting Ink** (`mut`, `light-mut`): labels, source explanations and status copy.

**The Two Oranges Rule.** Use the text accent for links, values and focus, and the action orange for filled actions, checkboxes and selection marks. Day mode keeps these separate so orange text stays readable.

The error status uses its own theme-aware warm red treatment. Photographic previews, histogram traces, semantic hue/tone slider ramps and user-editable sheet colors are content; they do not create secondary UI brand colors.

## Typography

**Brand Font:** Barlow Condensed, with sans-serif fallback, bundled locally at medium and semibold weights.
**Body Font:** the platform sans stack, including PingFang SC for Chinese.
**Value Font:** IBM Plex Mono, with monospace fallback, bundled locally at regular weight.

The condensed wordmark gives the tool its identity. Working labels remain compact and familiar; mono readouts make dimensions, counts and adjustments easy to scan. There is no large editorial display scale in the shared UI.

### Hierarchy

- **Brand** (`brand`): wordmark at the desktop size; it steps down to (21px) below (800px) and (18px) below (620px).
- **Title** (`title`): the active inspector pane heading.
- **Section** (`section`): frame-rail and processing group headings. The inherited processing title retains its own heavier weight.
- **Body** (`body`): controls, navigation and explanatory content.
- **Label** (`label`): field labels, notes and frame titles. Notes use a looser line height (1.7); source sublabels remain smaller (11px).
- **Value** (`value`): counts, crop and export dimensions, zoom and adjustment readouts. Use tabular numerals.

The empty-state heading (22px) and help title (20px) are local informational roles, not a reusable display hierarchy. Exported sheet lettering is a separate renderer concern: Barlow Condensed, IBM Plex Mono, a drawn dot-matrix style and licensed CJK fallback are selectable approximations rather than manufacturer-exact typefaces.

## Layout

**The Image Leads Rule.** Keep the photograph or rendered sheet in the largest continuous region; control groups belong beside or below it.

Use continuous regions separated by fine rules rather than a grid of cards. The shared fixed header is (64px) high, changing to (60px) below (800px). The sheet workspace uses a frame rail, a flexible central stage and an inspector; its desktop columns are (224px), `minmax(300px, 1fr)` and (336px). At (1600px) and above the side regions widen to (248px)/(360px); at (1150px) and below they reduce to (184px)/(310px). Hiding the rail returns that area to the stage. The processing inspector uses (344px), then (310px) and (292px) at its narrower breakpoints.

Below (800px), the sheet rail becomes a removable overlay and the inspector stays beside the stage. Below (620px), the stage precedes the full-width inspector in document flow. The sheet stage occupies (65dvh) with a (450px) minimum; the processing stage uses (70dvh) with a (440px) minimum. Inspector tabs stick beneath the header. The caption keeps a two-line roll identity (title and output dimensions) beside the view switch and photo-list button; the compact row gives the photograph more vertical room. View-switch, frame-caption and inspector-tab controls have a (42px) minimum height at this breakpoint. The mobile sheet status footer is static, and the frame overlay can extend to the viewport bottom.

Spacing is compact and contextual rather than a universal mathematical scale. Reused steps are recorded in the frontmatter; inspector padding is (24px 22px), paired fields use a (12px) gap, ordinary control gaps use (6px)/(8px), and a field group ends with a (17px) margin. Keep file names ellipsized within their row and wrap source paths and links. Desktop regions scroll independently; narrow screens scroll as a page.

## Elevation & Depth

**The Quiet Frame Rule.** Use flat tonal surfaces and fine borders for the working chrome. Reserve ambient lift for the displayed artifact, temporary help or the overlaid frame rail.

Control panels and toolbars are flat, opaque and separated by borders. The sheet preview and processing help card use the shared ambient shadow; the overlaid sheet rail has a lateral shadow. Processing photography retains its inherited image shadow and crop mask because they distinguish the image and unselected crop region. These content effects do not license shadows on every control.

### Shadow Vocabulary

- **Artifact / Help:** `var(--shadow)`, night (`0 14px 36px #0003`) and day (`0 12px 32px #28242018`).
- **Overlay Rail:** (`8px 0 22px #0003`), only when the frame rail overlays the stage.
- **Processing Image:** inherited (`0 10px 40px rgba(0, 0, 0, 0.7)`), specific to the image wrapper.
- **Crop Mask:** inherited (`0 0 0 4000px rgba(0, 0, 0, 0.6)`), a functional mask outside the selection.

The inherited help modal has an (8px) backdrop blur for temporary separation. Permanent stage toolbars explicitly remove backdrop filters and shadows.

## Shapes

**The Measured Cut Rule.** Keep controls square. Confine the angular cut to important actions and mounting details, preserving the source proportions rather than cutting every container.

Inputs, buttons, list containers and shared panels have square corners. Main actions clip opposite corners with an (8px) horizontal and (14px) vertical offset; the processing export/autocrop variant uses (6px)/(10px). Those source proportions give approximately (30°)/(60°) oblique edges. Do not substitute a generic (45°) chamfer.

Keep the preview free of decorative corner marks. Guides must support composition or an editing action. Crop handles are square orange markers (11px). Circular nodes belong to the SVG icon vocabulary; sheet range inputs use thin 3px tracks, 12px square orange handles and 26px interaction targets, while processing ranges and checkboxes retain their established geometry. The square-control rule does not ban those meaningful circles.

## Components

### Buttons

Filled actions are confident and sparse: use the action orange, dark ink, square/cut geometry and semibold text. Shared actions have (40px) minimum height, not a forced fixed height. Quiet actions use transparent fill, a one-pixel divider border and foreground text, with (36px) minimum height. Hover gives quiet actions the selection surface; primary hover uses its dedicated fill.

Icon buttons use the same border/surface states with a (36px) square footprint; the canvas toolbar uses (36px), with (34px) widths and (38px) minimum heights on narrow screens. Keyboard focus is a text-accent outline (2px) with a (3px) offset; the filled action increases the offset to (5px). Disabled controls reduce opacity to (.45). The inherited processing buttons also carry a brief active scale (.97); it is a processing behavior rather than a requirement for new sheet controls.

### Mode Selectors

The processing mode buttons retain their compact layout but their shared appearance is rectangular: neutral surface at rest, action orange when selected, no pill radius or resting shadow. The selected state also becomes semibold. Treat these as immediate settings, not decorative tags.

### Inputs / Fields

Fields use the field ground, foreground text and a one-pixel divider border, with square corners and (8px 10px) padding. The sheet text-field minimum height is (40px). Labels and supporting notes use muted ink; numeric outputs sit beside the label in mono accent text. Checkbox/range accents use action orange; tone and hue tracks may show their functional color ramps. Keep visible labels and preserve native editing behavior.

### Navigation

The shell uses two plain text destinations with small SVGs. Active destinations change from supporting to main ink and get a (3px) orange underline; inspector tabs use a (2px) underline. At narrow widths, navigation SVGs and the brand caption disappear while text destinations remain. The day/night button stores the selected theme and describes the mode it will switch to. The photo-list toggle exposes its expanded state; narrow layouts use a dismissible backdrop, contain keyboard focus in the temporary drawer, and restore focus when it closes. Collapsing the desktop rail returns a real two-column grid to the canvas and inspector.

**The Node Grammar Rule.** Draw navigation and action icons as inline SVG strokes with simple paths and occasional circular connection nodes.

Shell icon strokes use (1.65px) with rounded line caps and joins; the wordmark symbol uses (1.5px). Stroke roundness is independent of control corners.

### Inspector Sections

Use an opaque panel surface, a fine boundary rule and grouped fields. The six inspector tabs are 胶卷, 布局, 照片, 背景, 信息 and 导出. The active pane exposes one settings family at a time; the separate 照片 pane contains single-frame composition controls, and an export action stays in the inspector footer. This is a region of the workbench, not a floating card collection.

### Frame Rows

A frame row pairs selection, a real thumbnail, an ellipsized file name, source provenance and order. Active rows use the selection surface with an accent title; drag targets get a one-pixel accent outline. The desktop thumbnail is (54px × 39px), reducing to (42px × 32px) below (1150px). Activating a row opens the single-frame view and its 照片 inspector pane; the narrow photo rail closes so the composition remains visible. A circular edited marker in processing is a meaningful data state, distinct from action icons.

### Preview and Progress

The stage caption offers 整卷 / 单张 as a square segmented switch. The selected view uses the neutral selection surface and readable orange text, rather than an orange fill. Its buttons are at least (36px) high on desktop and (40px) on narrow screens; hover uses foreground ink. The single-frame view is disabled while no photos are available or preparation is in progress.

The single-frame canvas supports quarter-turn rotation, crop-center dragging, composition scale and horizontal/vertical center sliders. Dragging is enabled when scaling or a cover fill leaves image pixels outside the window; the pointer changes from grab to grabbing during the gesture. The bottom toolbar provides previous/next navigation and inclusion in the roll alongside undo/redo. The bottom toolbar groups edit history with previous/next and roll inclusion in this view. Roll zoom and refresh controls are hidden here; the 照片 pane owns composition scale.

The composition canvas uses a (1200px) thumbnail source and a (1200px)-wide canvas, fitted to the available stage. It applies the same per-frame rotation, fit, crop center and crop scale parameters as the roll renderer and export. This is a composition preview rather than a full-resolution inspection. Optional dashed thirds guides are drawn only on this preview canvas and are never exported.

Show the actual rendered roll artifact, including a checkerboard for transparency. Preview replacement uses a filter transition (120ms ease-out) and dims pending content to brightness (.78); the prepare bar animates width (180ms ease-out). Respect reduced motion by removing transitions and animation. Do not add unrelated entrance motion to the workbench.

## Do's and Don'ts

### Do:

- **Do** use the shared theme variables for text, fields, borders and panel backgrounds in both workspaces.
- **Do** keep the central photograph or sheet uninterrupted, with controls organized by the action they perform.
- **Do** use the muted text token for supporting copy and the foreground token for editable values and file names.
- **Do** retain square controls, fine alignment lines and the measured action cut.
- **Do** use inline SVG icons and text labels for visible actions; preserve focus and disabled states.
- **Do** stack the stage and inspector on narrow screens and leave the mobile status footer in document flow.
- **Do** keep film edge lettering and exported sheet backgrounds editable; identify approximate lettering as an approximation.

### Don't:

- **Don't** turn the workbench into a fake machine bezel, terminal, dashboard or promotional page.
- **Don't** use bright filled orange for long labels or body copy; use the theme's text accent for orange text.
- **Don't** add rounded card chrome, glass panels or decorative glows to new controls.
- **Don't** promote inherited glyph icons, isolated rounded legacy widgets or hard-coded legacy colors into the shared system.
- **Don't** impose the workbench chrome palette on user-editable photographic backgrounds or archival sheet content.
- **Don't** replace the recorded direction key with an invented seed.

**Not canonized:** inherited Unicode action glyphs, localized legacy hard-coded colors, the edited-dot glow and isolated rounded histogram/image widgets remain implementation drift. They are not new shared tokens or rules, and this documentation pass does not repair code. Documentation uses the corrected current source. Final desktop/day/narrow review captures are stored as `.impeccable/review/final-*.jpg`; older captures are historical evidence.

### 边字与片头

- 边字包含 Citaro Voor 常规／双高度（Jeffrey Visser，CC BY-SA 3.0）、自绘曝光圆点／窄条连印，以及原有点阵、Barlow 窄体和 IBM Plex 等宽字。字体样张由导出渲染器生成；自绘字是风格模拟，不是厂家字体。
- 片头按画格加入照片之前。自动模式使用最少的正数格数补齐末行；照片本来满行时增加一行片头。手动模式可指定 0–24 格，保留末行实际长度。片头不消耗照片帧号或逐张裁剪索引。
- 片头有暗片、透明片基、暖色漏光、曝光灼白和上下放射漏光，可调曝光强度，并选弧形裁切或完整直边。用整个片头的连续坐标生成曝光场，包含齿孔边带；左强右弱，照片前淡回片基色，不逐格绘制色块。
- 顶栏采用更饱满的中等字重信息字，按实际字段长度分配宽度；可显示胶卷型号与 ISO、调整信息字号。所有新设置随草稿、版式与项目保存。

### 配色与胶片条层次

- 颜色入口使用命名色卡和明确的自定义 HEX 输入，不调用原生取色弹窗。背景、片基、边字、横幅和文字各有适合其用途的推荐色；渐变搭配一次更新两色，并作为一次可撤销编辑。
- 背景不透明度独立于片条、照片和横幅。透明区域在预览中显示棋盘格，PNG 保留 alpha，JPEG 合成白底。
- 柔和投影、浅色细边、细边加投影、纸白衬边均为可选的作品效果，不是界面装饰。效果仅沿片条外轮廓绘制，不堵住齿孔；复用片头裁切轮廓，强度可调。
- 色卡、强度和说明沿用昼夜主题的文字与边界 token；窄屏保持四列色卡、两列渐变搭配，不产生横向滚动。
