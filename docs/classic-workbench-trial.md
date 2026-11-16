# Classic workbench trial · 2026-11-16

The first acceptance target is the native Mac app. This trial is on `codex/classic-workbench-v1`; it is not a main-branch release.

## Native behavior

- Bottom filmstrip by default; clicking an already selected frame changes the active photo without collapsing the selection. Existing position preferences remain honored.
- Left: presets, tonal styles and session history. Right: Basic, Curves, HSL, Detail, Effects, Film inversion and Advanced. Crop is a tool above the panels. Export settings open separately.
- A fixed action bar contains Copy, Paste, Sync, Reset and Auto Sync. Multi-selection alone never enables Auto Sync.
- Sync supports individual parameters, including each HSL color/channel. Exposure, Gamma, crop, orientation and sampling regions are excluded from the common selection.
- Auto Sync captures its target set when an edit starts and applies only changed fields after the gesture. Rotation and emulsion correction operate on each frame's own geometry.
- Sync/paste/auto-sync transactions have durable undo receipts, redo receipts and conflict checks. Ordinary session history survives active-photo changes. The history list is informational; it does not yet support jumping to arbitrary entries.
- Roll crop/Gamma retain their existing analysis/review workflow. Applying a single-photo Gamma recommendation remains single-photo even with Auto Sync enabled.

## Trial bundle

Build with a separate application identifier and optional isolated data root:

```sh
NM_CLASSIC_PREVIEW=1 NM_DATA_ROOT="/absolute/trial/data" FilmDecastSwift/build-app.sh "/absolute/NegativeMaster Classic Preview.app"
```

The shipped local trial is in `work/classic-trial/NegativeMaster Classic Preview.app`. Its app preferences, presets and archive are isolated from the production app. Normal edits still save XML next to whichever photos the user opens; UI tests used only generated fixtures under `work/classic-trial/photos`.

## Verification

- Native Swift suite: 38 passed; final release build and ad-hoc code signing succeeded.
- Python full suite: 191 run, 2 skipped. After the final undo conflict hardening, the 35 relevant native transport and web-adapter tests passed again.
- JavaScript suite: 51 passed.
- Actual Mac UI: opened generated four-frame roll, selected all, changed active frame without losing selection, edited one exposure with Auto Sync off, synchronized highlights with Auto Sync on, checked another frame's distinct exposure, undid/redid the batch after switching frames, and undid/redid a single-photo edit after switching frames. Final relaunch confirmed history refresh and removal of duplicate filters.
- Screenshots: `work/classic-trial/native-workbench.png`, `work/classic-trial/native-sync.png` (the latter is from the first UI pass, before sync-group reordering).
- Mac dark appearance and minimum-size layout were not revalidated in this pass. No new performance benchmark or real RAW-roll acceptance is claimed.

## Web work

Shared granular sync/geometry/undo endpoints are tested. The new web action bar/history prototype is opt-in at `/?classic=1`; it received an initial layout check only. Full web interaction and responsive acceptance remain pending while native acceptance takes priority. The ordinary web route retains its prior interaction model.
