# Changelog

All notable changes to this project are documented in this file. The project
uses semantic versioning for plugin releases.

## [0.7.2] - 2026-08-01

### Fixed

- Pinned the first public version to the legacy `POST /data/...` contract at
  `api.jx3api.com` so existing Token credentials continue to work after the
  primary service migration; current-API adaptation is deferred.
- Route stale legacy media URLs through the selected backup host while keeping
  the existing host, redirect, MIME, byte, and pixel safety checks.
- Clear a stale startup error after an administrator corrects an invalid API
  base URL and the plugin initializes again.
- Convert Pillow decompression-bomb failures into bounded user-facing image
  errors instead of allowing an unhandled exception.
- Keep script- and style-only article content out of the safe-text fallback.

### Changed

- Hardened article-session ownership, bounded image canvases and long wrapped
  text, made food de-duplication linear, and made render cancellation cleanup
  deterministic.
- Organized internal Python modules into core and presentation packages without
  changing commands, configuration, or runtime behavior.
- Restricted asset synchronization and WebChat smoke tooling to explicitly
  approved hosts and bounded raster inputs.
- Prepared the project for its first public GitHub hosting with consistent
  metadata, CI dependencies, security guidance, and release-facing documents.

## [0.7.1] - 2026-07-21

### Changed

- Refined the single-mode arena profile layout while preserving the full-width
  fallback and multi-mode rendering.
- Aligned the current score, ranking, and MVP column in the compact arena card.

### Verified

- Passed the AstrBot 4.26.6 / Python 3.12.13 Docker import and isolated-load
  baseline for this release.
- Passed Ruff, Pyright, and 78 project tests at the time of the release build.

## [0.7.0] - 2026-07-20

### Added

- Added the article selection flow, local article rendering, fixed adventure
  and Baizhan thumbnails, and the compact single-mode arena profile layout.

### Changed

- Improved calendar, food, adventure, arena, gold-price, item-search, and trade
  presentation based on real API responses.
