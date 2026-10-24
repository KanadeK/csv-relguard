import argparse
import json
import sqlite3
import sys

from . import __version__
from .core import ConfigError, audit, load_config


def positive(value):
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate exact-text CSV keys and references offline."
    )
    parser.add_argument("config", help="version 1 TOML config")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--max-issues", type=positive, default=100)
    parser.add_argument("--max-field-chars", type=positive, default=1024 * 1024)
    parser.add_argument("--temp-dir", help="directory for disposable on-disk key indexes")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    try:
        report = audit(
            load_config(args.config),
            max_issues=args.max_issues,
            max_field_chars=args.max_field_chars,
            temp_dir=args.temp_dir,
        )
        data = report.to_dict()
        if args.format == "json":
            print(json.dumps(data, ensure_ascii=True, indent=2))
        else:
            for issue in data["issues"]:
                row = f" row {issue['row']}" if "row" in issue else ""
                print(f"{json.dumps(issue['table'])}{row}: {issue['code']}: {issue['message']}")
            print(
                f"{data['issue_count']} issue(s), {data['omitted_issues']} omitted; "
                f"{data['relationships_checked']} relationship(s) checked, "
                f"{data['relationships_skipped']} skipped"
            )
        return 2 if report.io_errors else (0 if data["ok"] else 1)
    except (ConfigError, OSError, sqlite3.Error, OverflowError) as exc:
        print(f"csv-relguard: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
