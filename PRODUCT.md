# NegativeMaster

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The owner photographs film negatives, adjusts individual frames, and exports photographs and full-roll contact sheets locally on Windows, macOS or Linux. The SwiftUI front end remains macOS-only.

## Product Purpose

Convert camera-scanned negatives into positives, retain per-frame edits, and assemble editable film-strip presentations of a roll.

The film archive workspace adds durable local roll records: dates, places, camera/lens, stock and exposure index, development, tags, physical negative storage, source-linked frames, ratings and notes. SQLite metadata and managed preview assets stay separate from original images and adjustment sidecars. Archive ZIP backups carry metadata and previews, not originals. Covers retain optional attribution/source links; generated stock labels are explicitly not authentic packaging.

## Operating Context

Python Flask app on localhost:8765, Pillow/NumPy/rawpy processing. Existing RAW/JPEG inputs, XML adjustment sidecars, saved settings, and positive exports are real user content.

## Capabilities and Constraints

Preserve existing inversion, color and tone controls, crop/level, presets, matching, per-image memory, and batch exports. Contact sheets default to exported positive files; missing exports are generated using saved per-frame adjustments. Add film models and editable edge inscriptions, frame numbering, backgrounds (blurred photo, solid, gradient, transparent), optional archival white header, order editing, and high-resolution image exports. Manufacturer-specific exact edge lettering/font evidence is incomplete; reconstructions must be identified and editable. No cloud upload is needed.

## Brand Commitments

User requests bright orange, ordinary orange, dark gray and black, a day mode, sharp corners, 30°/60° control details and horizontal/vertical guides. Q Graph's content-first structure and node icon grammar are explicitly requested. Supplied film-strip and archival sleeve images govern the exported composition and header.

## Evidence on Hand

Current gui.py and decast.py, two locally edited rolls, XML sidecars and *_pos.jpg exports. Two user-supplied reference photographs. Film stock existence and edge lettering research will include source URLs; uncertain letterforms are approximations.

## Product Principles

- The photograph or sheet receives the largest uninterrupted area.
- Controls describe real actions and show processing progress and recoverable errors.
- Real saved edits and exported images drive previews and final exports.
- Crop and lettering choices remain adjustable; approximations do not masquerade as historical evidence.
