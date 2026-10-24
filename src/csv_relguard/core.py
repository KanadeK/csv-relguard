"""Exact-text relational checks with disposable, disk-backed key indexes."""

import csv
import json
import sqlite3
import tempfile
import tomllib
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath


class ConfigError(ValueError):
    pass


@dataclass
class Table:
    name: str
    path: Path
    key: list[str]
    delimiter: str = ","


@dataclass
class Relationship:
    source: str
    columns: list[str]
    target: str
    allow_empty: bool = False


@dataclass
class Config:
    tables: dict[str, Table]
    relationships: list[Relationship]


def columns(value, label, allow_empty=False):
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ConfigError(f"{label} must be a list of column names")
    if any(not isinstance(x, str) or not x for x in value) or len(set(value)) != len(value):
        raise ConfigError(f"{label} must contain distinct nonempty names")
    return value


def exact_fields(value, allowed, label):
    if not isinstance(value, dict) or set(value) - allowed:
        raise ConfigError(f"Invalid or unknown fields in {label}")


def load_config(path):
    path = Path(path).resolve()
    with path.open("rb") as source:
        raw = source.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ConfigError("Config exceeds 1 MiB")
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError("Config must be valid UTF-8 TOML") from exc
    exact_fields(data, {"version", "tables", "relationships"}, "config")
    if type(data.get("version")) is not int or data["version"] != 1:
        raise ConfigError("Config version must be 1")
    raw_tables = data.get("tables")
    if not isinstance(raw_tables, dict) or not 1 <= len(raw_tables) <= 128:
        raise ConfigError("Config needs 1..128 named tables")
    tables = {}
    for name, spec in raw_tables.items():
        if not name:
            raise ConfigError("Table name must not be empty")
        exact_fields(spec, {"path", "key", "delimiter"}, f"table {name}")
        relative = spec.get("path")
        if not isinstance(relative, str) or not relative or "\x00" in relative:
            raise ConfigError(f"Table {name} needs a relative path")
        if PureWindowsPath(relative).drive or Path(relative).is_absolute():
            raise ConfigError("CSV paths must be relative to the config directory")
        target = (path.parent / relative).resolve()
        if not target.is_relative_to(path.parent):
            raise ConfigError("CSV paths must remain inside the config directory")
        delimiter = spec.get("delimiter", ",")
        if not isinstance(delimiter, str) or len(delimiter) != 1 or delimiter in '\r\n\x00"':
            raise ConfigError("Delimiter must be one character other than newline, NUL or quote")
        tables[name] = Table(
            name, target, columns(spec.get("key", []), "key", allow_empty=True), delimiter
        )
    raw_relations = data.get("relationships", [])
    if not isinstance(raw_relations, list) or len(raw_relations) > 512:
        raise ConfigError("relationships must be a list with at most 512 entries")
    relationships = []
    for spec in raw_relations:
        exact_fields(spec, {"source", "columns", "target", "allow_empty"}, "relationship")
        source, target = spec.get("source"), spec.get("target")
        if not isinstance(source, str) or source not in tables:
            raise ConfigError("Relationship source must name a declared table")
        if not isinstance(target, str) or target not in tables or not tables[target].key:
            raise ConfigError("Relationship target must declare a nonempty key")
        cols = columns(spec.get("columns"), "relationship columns")
        if len(cols) != len(tables[target].key):
            raise ConfigError("Relationship columns and target key must have equal lengths")
        allow_empty = spec.get("allow_empty", False)
        if type(allow_empty) is not bool:
            raise ConfigError("allow_empty must be boolean")
        relationships.append(Relationship(source, cols, target, allow_empty))
    if not any(t.key for t in tables.values()) and not relationships:
        raise ConfigError("Declare at least one key or relationship to check")
    return Config(tables, relationships)


@dataclass
class Report:
    max_issues: int
    issue_count: int = 0
    issues: list[dict] = field(default_factory=list)
    tables: dict = field(default_factory=dict)
    relationships_checked: int = 0
    relationships_skipped: int = 0
    io_errors: int = 0

    def add(self, code, table, message, **details):
        self.issue_count += 1
        if len(self.issues) < self.max_issues:
            self.issues.append(dict(code=code, table=table, message=message, **details))

    def to_dict(self):
        return dict(
            schema_version=1,
            ok=self.issue_count == 0,
            issue_count=self.issue_count,
            omitted_issues=self.issue_count - len(self.issues),
            issues=self.issues,
            tables=self.tables,
            relationships_checked=self.relationships_checked,
            relationships_skipped=self.relationships_skipped,
            io_errors=self.io_errors,
        )


def packed(values):
    """Length-safe tuple serialization; never concatenate with a user-data delimiter."""
    return json.dumps(values, ensure_ascii=True, separators=(",", ":"))


def load_table(db, table, table_id, relations, report):
    summary = {"rows": 0, "complete": False}
    report.tables[table.name] = summary
    try:
        with table.path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.reader(source, delimiter=table.delimiter, strict=True)
            header = next(reader, None)
            if not header or any(not col for col in header) or len(set(header)) != len(header):
                report.add("header", table.name, "Header must have unique nonempty column names.")
                return
            required = set(table.key)
            for _, relation in relations:
                required.update(relation.columns)
            missing = sorted(required - set(header))
            if missing:
                report.add(
                    "missing-column", table.name, "Required columns are missing.", columns=missing
                )
                return
            positions = {name: i for i, name in enumerate(header)}
            record = 1
            while True:
                line = reader.line_num + 1
                values = next(reader, None)
                if values is None:
                    break
                record += 1
                summary["rows"] += 1
                if len(values) != len(header):
                    report.add(
                        "row-width",
                        table.name,
                        "Row width differs from the header.",
                        row=record,
                        line=line,
                        expected=len(header),
                        actual=len(values),
                    )
                    # Partial key indexes must never produce authoritative orphan findings.
                    summary["invalid_rows"] = summary.get("invalid_rows", 0) + 1
                    continue
                if table.key:
                    key = [values[positions[col]] for col in table.key]
                    if "" in key:
                        report.add(
                            "empty-key",
                            table.name,
                            "Key contains an empty cell.",
                            row=record,
                            line=line,
                            columns=table.key,
                        )
                    else:
                        try:
                            db.execute(
                                "INSERT INTO keys VALUES(?,?,?)", (table_id, packed(key), record)
                            )
                        except sqlite3.IntegrityError:
                            first = db.execute(
                                "SELECT first_row FROM keys WHERE table_id=? AND value=?",
                                (table_id, packed(key)),
                            ).fetchone()[0]
                            report.add(
                                "duplicate-key",
                                table.name,
                                "Key was already seen.",
                                row=record,
                                line=line,
                                first_row=first,
                                columns=table.key,
                            )
                for relation_id, relation in relations:
                    key = [values[positions[col]] for col in relation.columns]
                    if "" in key:
                        if relation.allow_empty and all(v == "" for v in key):
                            continue
                        report.add(
                            "empty-reference",
                            table.name,
                            "Reference contains an empty cell.",
                            row=record,
                            line=line,
                            relationship=relation_id + 1,
                            columns=relation.columns,
                        )
                    else:
                        db.execute(
                            "INSERT INTO refs VALUES(?,?,?,?)",
                            (relation_id, packed(key), record, line),
                        )
            summary["complete"] = not summary.get("invalid_rows", 0)
    except (csv.Error, UnicodeDecodeError) as exc:
        report.add(
            "csv-input",
            table.name,
            "Invalid CSV, UTF-8, or field size limit exceeded.",
            error_type=type(exc).__name__,
        )
    except OSError as exc:
        report.io_errors += 1
        report.add(
            "input-error", table.name, "Cannot read CSV input.", error_type=type(exc).__name__
        )


def audit(config: Config, *, max_issues=100, max_field_chars=1024 * 1024, temp_dir=None):
    if max_issues < 1 or max_field_chars < 1:
        raise ValueError("Limits must be positive")
    report = Report(max_issues)
    previous_limit = csv.field_size_limit()
    csv.field_size_limit(max_field_chars)
    try:
        with tempfile.TemporaryDirectory(prefix="csv-relguard-", dir=temp_dir) as work:
            with closing(sqlite3.connect(Path(work) / "keys.sqlite")) as db:
                db.executescript("""
                    PRAGMA journal_mode=OFF;
                    PRAGMA temp_store=FILE;
                    PRAGMA cache_size=-8192;
                    CREATE TABLE keys(table_id INTEGER, value TEXT, first_row INTEGER,
                                      PRIMARY KEY(table_id,value)) WITHOUT ROWID;
                    CREATE TABLE refs(relation INTEGER, value TEXT, row INTEGER, line INTEGER);
                    CREATE INDEX refs_relation ON refs(relation);
                """)
                table_ids = {name: i for i, name in enumerate(config.tables)}
                for name, table in config.tables.items():
                    outgoing = [
                        (i, r) for i, r in enumerate(config.relationships) if r.source == name
                    ]
                    load_table(db, table, table_ids[name], outgoing, report)
                    db.commit()
                for i, relation in enumerate(config.relationships):
                    if not all(
                        report.tables[t]["complete"] for t in (relation.source, relation.target)
                    ):
                        report.relationships_skipped += 1
                        report.add(
                            "relationship-skipped",
                            relation.source,
                            "Source or target was not fully indexed; no orphan conclusion.",
                            relationship=i + 1,
                            target=relation.target,
                        )
                        continue
                    report.relationships_checked += 1
                    rows = db.execute(
                        """
                        SELECT r.row,r.line FROM refs r LEFT JOIN keys k
                        ON k.table_id=? AND k.value=r.value
                        WHERE r.relation=? AND k.value IS NULL ORDER BY r.row
                    """,
                        (table_ids[relation.target], i),
                    )
                    for row, line in rows:
                        report.add(
                            "orphan-reference",
                            relation.source,
                            "Reference has no matching target key.",
                            row=row,
                            line=line,
                            relationship=i + 1,
                            target=relation.target,
                            columns=relation.columns,
                        )
    finally:
        csv.field_size_limit(previous_limit)
    return report
