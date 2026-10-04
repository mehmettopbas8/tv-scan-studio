# Changelog

## 0.2.0-rc.2 — preview

- Three primary screens: Strategies, Scan and Results; general settings and task/backup tools remain accessible.
- Anchored first-use popup tours, source deduplication and explicit copy creation, readable input names, symbol/timeframe selection and wheel-safe controls.
- Guarded automatic preparation of independent saved test charts, source identity checks, connection guidance and hidden helper failure containment. Personal charts are not assigned automatically.
- Restore multi-graph selection (1–16), measured tests/hour, saved presets, optional local research imports, result filters and explicit export scopes.
- Excel defaults for archive exports, readable XLSX widths and Turkish UTF-8 CSV with semicolon separators and localized typed scalars.
- Count only verified completions, not retry attempts, in worker throughput; prevent numeric-range endpoint overshoot and reject non-finite range fields.
- Release metadata, tags and package names now derive from the package version; Windows CI checks the hidden helper as well as self/UI probes.

This is an unsigned prerelease. Packaged interruption/recovery, empty-user live acceptance, date coverage, clean-Windows behavior and multi-worker performance remain separate acceptance gates. External research/report files are not included in current DB/Pine backups. Immutable scan runs, reevaluation, full contextual help, optional sampling, constraints and separate-period research are planned, not shipped here. See README for known limitations.

## 0.2.0-rc.1 — preview

- Move the packaging launcher under tools/ and add step-by-step EXE download, verification, first-run, update and removal instructions, including the development Actions artifact path before a Release exists.
- Package Windows builds as a single self-contained EXE; publish direct EXE/checksum and an optional one-EXE ZIP, without an adjacent `_internal` folder. Runtime extraction uses the Windows temporary directory; persistent user data stays in AppData.
- Added multi-project worker assignment on chart tabs sharing the single CDP 9222 session.
- Added persistent Pine identity and source-hash binding, including guarded temporary opening/restoration of a closed worker Pine panel. Existing editors are preserved; unavailable source still requires explicit user confirmation and is not automatic equality evidence.
- Added operational dashboard controls, retry/recovery, resource projections and worker restart supervision.
- Added FTMO profiles, editable cost assumptions and staged robustness validation.
- Reject fixed direct-input order quantity conflicts with the default Properties quantity; preserve explicit quantity scans and document the limits of computed-sizing verification.
- Added interactive trade analytics, preset comparison, CSV/Excel export and success-only PDF reports, plus checksummed backups.
- Added new-file-only backup restoration with SQLite, foreign-key and project/Pine consistency validation; backup sources now come from the same database snapshot. The active database is never replaced or switched by restoration.
- Preserve exact Pine line endings in new backups and support the known text-mode newline conversion in legacy Windows backups without accepting unrelated source changes.
- Prioritized the result list before the scatter chart and retained a readable minimum table height on compact result pages.
- Added task-bound dated Deep reports with fresh XLSX identity/input/cost verification and Strategy Properties commission/slippage application.
- Restored saved scan settings on project selection, isolated project defaults, and corrected minute/hour resolution mapping.
- Excluded private research archives from public source and portable packages; missing optional archives are handled explicitly.
- Added a portable Windows build self-test plus versioned ZIP and SHA-256 release generation.

The first public portable build is unsigned and may trigger Windows SmartScreen.
