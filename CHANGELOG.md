# Changelog

## 0.2.0 — release candidate, not yet published

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
