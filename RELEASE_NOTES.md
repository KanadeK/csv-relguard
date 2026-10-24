# v0.1.0

Initial release of a local CSV relational preflight tool.

- Strict TOML manifests, single/composite keys, optional and self references.
- Exact-text equality: leading zeros, whitespace and case remain significant.
- Disk-backed SQLite indexing and value-free row diagnostics.
- Strict CSV loading, BOM support, malformed-input handling and partial-index safeguards.
- JSON/text reports, capped examples and CI exit codes; no runtime dependencies.

20 behavioral tests passed against the installed wheel, including a generated
40,000-record relational case, alongside lint, formatting, wheel/sdist builds and
the README's good/bad examples. CI covers Linux/Windows and Python 3.11/3.13/3.14.

Limitations: exact declared relationships only, no data type/schema inference or
repair. Temporary indexes contain key values and cleanup is not secure erasure.
Use SHA256SUMS to verify downloaded packages. No PyPI publication is included.
