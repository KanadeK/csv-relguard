import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from csv_relguard.core import Config, ConfigError, Relationship, Table, audit, load_config


class RelationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def csv(self, name, content):
        p = self.root / name
        p.write_text(content, encoding="utf-8", newline="")
        return p

    def config(self, parents="id\n001\n1\n", children="pid\n001\n1\n", optional=False):
        return Config(
            {
                "parent": Table("parent", self.csv("parent.csv", parents), ["id"]),
                "child": Table("child", self.csv("child.csv", children), []),
            },
            [Relationship("child", ["pid"], "parent", optional)],
        )

    def test_exact_text_no_inference(self):
        self.assertTrue(audit(self.config()).to_dict()["ok"])
        d = audit(self.config("id\n001\n", "pid\n1\n 001\n")).to_dict()
        self.assertEqual(d["issue_count"], 2)
        self.assertTrue(all(i["code"] == "orphan-reference" for i in d["issues"]))

    def test_duplicate_and_empty_primary_keys(self):
        d = audit(self.config("id,label\na,x\na,y\n,z\n", "pid\na\n")).to_dict()
        self.assertEqual([i["code"] for i in d["issues"]], ["duplicate-key", "empty-key"])
        self.assertEqual(d["issues"][0]["first_row"], 2)

    def test_composite_serialization_has_no_delimiter_collision(self):
        cfg = Config(
            {
                "p": Table("p", self.csv("p.csv", "x,y\na|b,c\na,b|c\n"), ["x", "y"]),
                "c": Table("c", self.csv("c.csv", "a,b\na|b,c\na,b|c\n"), []),
            },
            [Relationship("c", ["a", "b"], "p")],
        )
        self.assertTrue(audit(cfg).to_dict()["ok"])

    def test_optional_reference(self):
        cfg = self.config("id\nx\n", 'pid\n""\n', optional=True)
        self.assertTrue(audit(cfg).to_dict()["ok"])
        cfg.relationships[0].allow_empty = False
        self.assertEqual(audit(cfg).issues[0]["code"], "empty-reference")

    def test_partial_empty_composite_is_not_nullable(self):
        cfg = Config(
            {
                "p": Table("p", self.csv("p.csv", "x,y\na,b\n"), ["x", "y"]),
                "c": Table("c", self.csv("c.csv", "a,b\na,\n,,\n"), []),
            },
            [Relationship("c", ["a", "b"], "p", True)],
        )
        d = audit(cfg).to_dict()
        self.assertEqual(d["issues"][0]["code"], "empty-reference")
        self.assertIn("row-width", [i["code"] for i in d["issues"]])
        self.assertEqual(d["relationships_skipped"], 1)

    def test_multiline_rows_and_physical_lines(self):
        cfg = self.config("id\na\n", 'pid,note\na,"one\ntwo"\nb,three\n')
        issue = audit(cfg).issues[0]
        self.assertEqual((issue["row"], issue["line"]), (3, 4))

    def test_header_errors_suppress_orphans(self):
        for content in ["id,id\na,b\n", "other\na\n", "\n", "id,\na,b\n"]:
            with self.subTest(content=content):
                d = audit(self.config(content, "pid\nx\n")).to_dict()
                self.assertEqual(d["relationships_skipped"], 1)
                self.assertNotIn("orphan-reference", [i["code"] for i in d["issues"]])

    def test_bad_row_suppresses_partial_target_conclusions(self):
        d = audit(self.config("id\na,b\n", "pid\na\n")).to_dict()
        self.assertFalse(d["tables"]["parent"]["complete"])
        self.assertEqual(d["relationships_checked"], 0)

    def test_malformed_csv_and_encoding(self):
        cfg = self.config('id\n"unclosed', "pid\nx\n")
        self.assertEqual(audit(cfg).issues[0]["code"], "csv-input")
        cfg.tables["parent"].path.write_bytes(b"id\n\xff\n")
        self.assertEqual(audit(cfg).issues[0]["code"], "csv-input")

    def test_missing_file(self):
        cfg = self.config()
        cfg.tables["parent"].path.unlink()
        d = audit(cfg).to_dict()
        self.assertEqual(d["io_errors"], 1)
        self.assertFalse(d["ok"])

    def test_bom_semicolon_and_quotes(self):
        cfg = Config(
            {"p": Table("p", self.csv("p.csv", '\ufeffid;note\n"a;b";hello\n'), ["id"], ";")}, []
        )
        self.assertTrue(audit(cfg).to_dict()["ok"])

    def test_cap_does_not_cap_counts(self):
        d = audit(self.config("id\na\n", "pid\nx\ny\nz\n"), max_issues=1).to_dict()
        self.assertEqual((d["issue_count"], len(d["issues"]), d["omitted_issues"]), (3, 1, 2))

    def test_temp_cleanup_and_input_unchanged(self):
        cfg = self.config()
        snapshot = {name: t.path.read_bytes() for name, t in cfg.tables.items()}
        scratch = self.root / "scratch"
        scratch.mkdir()
        audit(cfg, temp_dir=scratch)
        self.assertEqual(list(scratch.iterdir()), [])
        self.assertEqual(snapshot, {name: t.path.read_bytes() for name, t in cfg.tables.items()})

    def test_limit_restored(self):
        before = csv.field_size_limit()
        d = audit(self.config("id\nabcdef\n"), max_field_chars=3).to_dict()
        self.assertIn("csv-input", [i["code"] for i in d["issues"]])
        self.assertEqual(csv.field_size_limit(), before)

    def test_values_not_in_diagnostics(self):
        d = audit(self.config("id\nsecret-parent-123\n", "pid\nsecret-child-987\n")).to_dict()
        self.assertNotIn("secret-", json.dumps(d))

    def test_large_disk_backed_join(self):
        p = self.root / "p.csv"
        c = self.root / "c.csv"
        with p.open("w", newline="") as fp, c.open("w", newline="") as fc:
            wp, wc = csv.writer(fp), csv.writer(fc)
            wp.writerow(["id"])
            wc.writerow(["pid"])
            for i in range(20000):
                wp.writerow([f"{i:07d}"])
                wc.writerow([f"{i:07d}"])
        cfg = Config(
            {"p": Table("p", p, ["id"]), "c": Table("c", c, [])}, [Relationship("c", ["pid"], "p")]
        )
        d = audit(cfg).to_dict()
        self.assertTrue(d["ok"])
        self.assertEqual(d["tables"]["c"]["rows"], 20000)

    def test_self_reference(self):
        p = self.csv("tree.csv", "id,parent\na,\nb,a\n")
        cfg = Config(
            {"tree": Table("tree", p, ["id"])}, [Relationship("tree", ["parent"], "tree", True)]
        )
        self.assertTrue(audit(cfg).to_dict()["ok"])


class ConfigCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "input.csv").write_text("id\n1\n")
        self.base = 'version=1\n[tables.a]\npath="input.csv"\nkey=["id"]\n'

    def load(self, text):
        p = self.root / "schema.toml"
        p.write_text(text)
        return load_config(p)

    def test_config_valid_relative_to_manifest(self):
        cfg = self.load(self.base)
        self.assertTrue(cfg.tables["a"].path.samefile(self.root / "input.csv"))
        self.assertTrue(audit(cfg).to_dict()["ok"])

    def test_bad_configs(self):
        texts = [
            self.base + "typo=1\n",
            self.base.replace("version=1", "version=true"),
            self.base.replace('key=["id"]', 'key=["id","id"]'),
            self.base.replace("input.csv", "../escape.csv"),
            self.base.replace("input.csv", "C:/private/data.csv"),
            "version=1\n[tables]\n",
            "not toml",
            self.base + '[[relationships]]\nsource="a"\ntarget="absent"\ncolumns=["id"]\n',
            self.base
            + '[[relationships]]\nsource="a"\ntarget="a"\ncolumns=["id"]\nallow_empty="yes"\n',
        ]
        for text in texts:
            with self.subTest(text=text), self.assertRaises(ConfigError):
                self.load(text)

    def test_cli_exits(self):
        p = self.root / "schema.toml"
        p.write_text(self.base)

        def invoke():
            return subprocess.run(
                [sys.executable, "-m", "csv_relguard", str(p), "--format", "json"],
                capture_output=True,
                text=True,
                timeout=15,
            )

        self.assertEqual(invoke().returncode, 0)
        (self.root / "input.csv").write_text("id\n1\n1\n")
        bad = invoke()
        self.assertEqual(bad.returncode, 1)
        self.assertEqual(json.loads(bad.stdout)["issues"][0]["code"], "duplicate-key")
        (self.root / "input.csv").unlink()
        self.assertEqual(invoke().returncode, 2)


if __name__ == "__main__":
    unittest.main()
