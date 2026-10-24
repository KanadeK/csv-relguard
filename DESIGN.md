# Design and acceptance

The core user workflow is to put a manifest beside exported tables, declare keys
and references, run the checker, correct the export and rerun before import.
Acceptance requires exact text equality, composite keys without delimiter
collisions, row diagnostics without values, repeatable CLI exit codes, and no
changes to source files. Malformed input must not silently create an authoritative
orphan result from a partially loaded parent table.

Python's CSV parser handles quoted and multiline fields. Fixed SQL identifiers
and parameterized values avoid SQL injection from user table names or cells.
Key tuples are serialized as JSON arrays, not concatenated. An on-disk SQLite
primary key detects duplicates; indexed joins find missing targets. Memory does
not retain all keys in a Python dictionary. The temporary database is disposable;
journaling is disabled only for this private derived data, never for user inputs.

Review checked type inference, BOM handling, full/partial null composite keys,
header failures, physical versus logical row numbers, exact SQL equality, config
typos and path escapes, findings caps, cleanup on exceptions, and limited tables.
Tests cover 20,000 parent plus 20,000 child records and installed CLI operation.
Known boundaries include mutable source files, OS temporary storage privacy,
per-field rather than whole-row limits, and process-global csv.field_size_limit.
