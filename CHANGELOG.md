# Changelog

All notable changes to Daily Trade Radar are documented in this file.

## Unreleased

### 2026-07-22

#### Added

- Added English Markdown output when the root JSON `language` field is `en` or starts with `en-`.
- Added Chinese and English Word (`.docx`) report generation from validated event JSON.
- Added Word sections for the daily assessment, radar table, priority actions, deduplication, event details, official sources, watchlist, and coverage gaps.
- Added clickable official-source links, repeating table headers, page numbers, fixed table geometry, and risk-level highlighting to Word reports.
- Added automatic removal of document author metadata, custom properties, and Word revision-session identifiers.
- Added `python-docx` as the Word-generation dependency and installed it in GitHub Actions.
- Added automated tests for English Markdown and bilingual Word output.

#### Changed

- Rebuilt the bundled Word template to remove corrupted Chinese text and metadata.
- Updated the README, Skill instructions, and output-schema reference with bilingual and Word-output usage.
- Expanded the automated test suite from two tests to four.

## 0.1.0-alpha - 2026-07-21

### Added

- Published the initial Daily Trade Radar Codex Skill.
- Added official-source research guidance, event scoring, JSON validation, deduplication, and Chinese Markdown generation.
- Added offline examples, workflow tests, GitHub Actions validation, an MIT license, and installation instructions.
