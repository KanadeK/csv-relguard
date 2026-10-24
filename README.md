# csv-relguard

Check keys and references across CSV exports **before importing them**. Keep
identifiers as exact text, including leading zeroes, case and whitespace. Declare
the relationships in a small TOML file and receive row diagnostics without
printing the key values.

Use it for a database migration handoff, related research tables, or a CI check
on a collection of exported CSVs. It checks declared relationships; it does not
infer a database schema or modify your data.

## Install and try

Python 3.11+ with SQLite in the standard library. No runtime dependencies or server.
Clone this repository and run from its directory:

```sh
python -m venv .venv
# POSIX: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .
csv-relguard examples/good.toml
csv-relguard examples/bad.toml --format json
```

The first audit exits 0. The second exits 1 and finds a duplicate order key,
an empty customer reference, and a reference to a missing customer. The good
example deliberately contains both `001` and `1` as different customer IDs.
`python -m csv_relguard` is an equivalent entry point.

You can also install a wheel from a GitHub release with
`python -m pip install <wheel-file>` after verifying `SHA256SUMS`.
This package is not published to PyPI. Uninstall with
`python -m pip uninstall csv-relguard`; remove the virtual environment when done.

## Describe your tables

```toml
version = 1

[tables.customers]
path = "customers.csv"
key = ["tenant", "id"]

[tables.orders]
path = "orders.csv"
key = ["id"]
# delimiter = ","  # One Unicode character; comma is the default.

[[relationships]]
source = "orders"
columns = ["tenant", "customer_id"]
target = "customers"
allow_empty = false
```

Paths resolve relative to the TOML directory, independent of the shell's working
directory. They must stay inside that directory, including after symlink
resolution. Absolute paths, parent escapes and unknown config fields fail.
Use a common parent directory for your manifest and CSV files. Up to 128 tables
and 512 relationships are supported; configs are limited to 1 MiB.

A target must declare a nonempty `key`. `columns` maps positionally to that
key and must have the same length. A source may omit its own key when only its
references need checking. Every declared key is unique and nonempty. Multiple
references and self-references are supported. A config with no checks fails.

`allow_empty=true` permits only a tuple whose **every** component is `""`.
Partially empty composite references still fail. Only empty cells count as empty;
strings such as `NULL`, spaces, `0` and `NA` remain literal identifiers.

CSV files require UTF-8 (a UTF-8 BOM is accepted), a header of distinct nonempty
names, matching row widths, and RFC-style double-quote escaping. Quoted newlines
are supported. Blank records fail the width check. No delimiter or type inference,
trimming, case folding, Unicode normalization, or formula evaluation occurs.

## Results and automation

```sh
csv-relguard schema.toml --format json --max-issues 20
csv-relguard schema.toml --temp-dir ./scratch --max-field-chars 1048576
```

Exit **0** means all declared checks passed, **1** means data findings (including
malformed CSV), **2** means invalid config, unreadable input or an execution error.
Config/execution errors go to stderr; a report is printed when input loading can
continue. Missing files also appear as `input-error` in that report and exit 2.

JSON output uses `schema_version: 1`. It includes table row counts and `complete`
flags, relationship counts, total issues, and a capped `issues` array.
`--max-issues` caps only displayed examples; all checks and counts continue.
`row` is the logical CSV record number (header is 1); `line` is the physical line
where that record starts. `first_row` locates the original duplicate key.
`relationship` is the 1-based position of the relationship in the config.
Names and column names are reported, while actual cell/key values are omitted.

If a header, row width, CSV syntax or encoding problem prevents a complete table
index, relationships involving that table are reported as `relationship-skipped`.
The program fails and avoids misleading orphan conclusions from a partial index.
Empty or duplicate keys are known data violations and do not stop other checks.

```python
from csv_relguard.core import audit, load_config

result = audit(load_config("schema.toml"), max_issues=20).to_dict()
print(result["ok"], result["issue_count"])
```

## Privacy, performance and boundaries

Key tuples and references live in an automatically cleaned temporary SQLite
database. RAM usage depends on the current CSV record, headers, capped findings
and SQLite's cache, rather than a Python set containing every key. Disk usage
grows with the keys/references; provide sufficient local space. No values are
uploaded or logged, but the temporary files contain values until cleanup.
Use `--temp-dir` on encrypted local storage if that matters; deletion is not
secure erasure. A forced process kill may leave temporary files to clean up.

The 1 Mi-character default **per field** limit is configurable; it is not a hard
whole-row or process memory limit. CSV parsing is strict, but not a sandbox for
hostile files. Audit static exports: files changed during a run are not a coherent
snapshot. The Python library temporarily changes `csv.field_size_limit` and
restores it; serialize calls within a process when using different limits.

[Frictionless](https://github.com/frictionlessdata/frictionless-py) is a broader
choice for typed schemas and complete data packages. pandas merge validation is
useful inside a dataframe workflow. This tool focuses on exact-text relational
preflight with no dependencies and disk-backed keys. It does not claim a new
relational validation algorithm or replace either project.

See [CONTRIBUTING.md](CONTRIBUTING.md), [DESIGN.md](DESIGN.md),
[validation/local.json](validation/local.json), [SECURITY.md](SECURITY.md),
[THIRD_PARTY.md](THIRD_PARTY.md), and [MIT license](LICENSE).
CI tests Linux and Windows on Python 3.11, 3.13 and 3.14.

## 中文说明

导入前检查多个 CSV 的主键与外键关系。通过 TOML 声明单列/复合键，精确保留
`001`、`1`、空格和大小写的差异。检查重复键、空键、孤立引用，以及重复表头、
缺列、行宽、UTF-8 和引号语法。诊断显示行号与列名，不显示单元格值。
完全本地运行，临时 SQLite 索引在正常退出时删除；临时文件不等于安全擦除。
先执行 `python -m pip install .`，再运行 `csv-relguard examples/good.toml`。
当前版本只做声明的关系检查，不做类型推断、字段模式校验或数据修复。
