# Web and native workbench parity — 2026-11-04

The Flask browser workbench now uses the native Python adapters for selective synchronization, emulsion orientation, batch patch validation, optimistic concurrency, durable undo receipts, bounded linear previews and on-demand detail rendering. Both front ends use the same frame-detection and conversion-advisor algorithms. The web UI presents per-frame Gamma results rather than one average applied indiscriminately to a roll.

## Browser behavior

- The inspector uses independently collapsible sections, compact sliders and inline HSL color chips. Crop/rotation, basic, curves, HSL, detail and effects precede film-specific controls.
- The photo rail supports RAW filtering, cached thumbnails, bottom placement, range/toggle selection and removal from the session list. Session removal leaves files and sidecars intact.
- Crop rectangles and sampling regions follow rotation/reflection. Full captures appear while cropping or sampling; ordinary viewing clips to the saved crop.
- Interactive preview decoding is bounded to 1500 pixels, with a smaller drag preview. Detail rendering runs independently and stale responses are discarded. Export always reloads the full source.
- Whole-roll crop/Gamma analysis produces per-frame results. Apply touches only the proposed fields, rejects changed sidecars and writes undo receipts. Sync groups are individually selectable; an empty selected-photo scope never silently applies to the roll.
- Successful batch JPEG exports write the same export manifest consumed by the native app, sheets and archive. Saved reference paths are resolved per frame. Navigating back to editing restores the session list and active photo.
- The archive defaults to JPEG-first indexing, with lightweight previews for missing exports. Click selects; Cmd/Ctrl toggles; Shift selects a range; double-click/Enter opens details. Removal only changes archive associations.

## Verification

Python regression coverage includes preview/export resolution separation, scoped apply and concurrency conflict, exact sidecar undo, idempotent emulsion mirroring, reference isolation, thumbnail dimensions, export manifests and analysis/detail cache isolation. JavaScript tests cover crop/reflection reversibility, selection semantics and bounded Gamma recommendations. Existing archive, sheet, saving and native bridge suites remain part of the regression run.

Browser QA uses synthetic images and a separate archive/settings root under ignored `work/web-parity/qa`. Confirmed: collapsible controls, Shift selection, crop-preserving rotation, whole-roll analysis, JPEG export/log creation, sheet handoff (three existing JPEGs plus one generated preview), archive indexing, single-click selection and double-click details, and returning to the editing session. Responsive desktop/mobile and day/night checks are included. Batch removal and undo data integrity are verified by automated backend tests.

No new native app bundle is installed for this web update. macOS physical wheel/drag testing is separate from these browser and backend checks; the previous native build's pending hardware checks are not implied to have passed.
