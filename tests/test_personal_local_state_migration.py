"""Offline local state migration safety tests; never invoke live providers."""
from pathlib import Path
from contextlib import closing
import json
import sqlite3
from tempfile import TemporaryDirectory
import unittest

import personal_local_state_migration as m


def cache(path, rows=(), extra=False):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(m.CACHE_SCHEMA)
        if extra:
            db.execute("CREATE TABLE other_original_data (id TEXT PRIMARY KEY)")
            db.execute("INSERT INTO other_original_data VALUES ('preserve')")
        for row in rows:
            db.execute(
                f"INSERT INTO validation_cache ({m.CACHE_FIELDS}) VALUES (?,?,?,?)",
                row,
            )


def rec(url, seen, *, reviewed="pending", judged=False, first=None):
    return {
        "url": url, "first_seen": first or seen, "last_seen": seen,
        "review_status": reviewed, "ai_judged": judged,
        "title": "Example", "source": "Mock",
    }


class StateMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        self.production = root / "ray-personal-job-discovery"
        self.experiment = root / "ray-provider-audit"
        self.release = root / "ray-expanded-release"
        for folder in (self.production, self.experiment, self.release):
            folder.mkdir()
        cache(self.production / m.CACHE,
              [("personal-fit-v1:sample:1", "old", '{"fit_score": 50}', "2026-10-16 20:00:00"),
               ("other-namespace:keep", "fp", '{"ok": true}', "2026-10-16 20:00:00")],
              extra=True)
        cache(self.experiment / m.CACHE,
              [("personal-fit-v1:sample:1", "new", '{"fit_score": 65}', "2026-10-17 10:00:00"),
               ("personal-fit-v1:sample:2", "pilot", '{"fit_score": 75}', "2026-10-17 11:00:00")])
        cache(self.release / m.CACHE, [])
        self.a = "https://jobs.example/item/a"
        self.b = "https://jobs.example/item/b"
        (self.production / m.HISTORY).write_text(json.dumps({
            self.a: rec(self.a, "2026-10-16T10:00:00Z", reviewed="applied"),
        }), encoding="utf-8")
        (self.experiment / m.HISTORY).write_text(json.dumps({
            self.a: rec(self.a, "2026-10-17T10:00:00Z", reviewed="applied"),
            self.b: rec(self.b, "2026-10-17T11:00:00Z", judged=True),
        }), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_migration(self, **kwargs):
        return m.migrate(
            production=self.production,
            experiment=self.experiment,
            release=self.release,
            **kwargs,
        )

    def test_dry_run_does_not_change_release_or_originals(self):
        old_prod = (self.production / m.CACHE).read_bytes()
        old_exp = (self.experiment / m.CACHE).read_bytes()
        old_rel = (self.release / m.CACHE).read_bytes()
        result = self.run_migration()
        self.assertEqual(result["mode"], "dry_run")
        self.assertEqual(result["history_union"], 2)
        self.assertEqual(result["history_decision_conflicts_total"], 0)
        self.assertEqual(result["sqlite_ambiguous_conflicts_total"], 0)
        self.assertEqual(result["sqlite_cache_records"]["combined"], 3)
        self.assertEqual((self.release / m.CACHE).read_bytes(), old_rel)
        self.assertEqual((self.production / m.CACHE).read_bytes(), old_prod)
        self.assertEqual((self.experiment / m.CACHE).read_bytes(), old_exp)
        self.assertFalse((self.release / m.HISTORY).exists())

    def test_apply_merges_newest_cache_retaining_original_other_tables(self):
        backup = self.release.parent / "user-private-backup"
        result = self.run_migration(apply=True, backup_dir=backup)
        self.assertTrue(result["release_written"])
        self.assertTrue((backup / m.CACHE).exists())
        self.assertEqual((self.release / m.HISTORY).exists(), True)
        with closing(sqlite3.connect(self.release / m.CACHE)) as db, db:
            self.assertEqual(db.execute(
                "SELECT fingerprint FROM validation_cache WHERE job_url=?",
                ("personal-fit-v1:sample:1",)).fetchone()[0], "new")
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM validation_cache").fetchone()[0], 3)
            self.assertEqual(db.execute(
                "SELECT id FROM other_original_data").fetchone()[0], "preserve")
        states = json.loads((self.release / m.HISTORY).read_text(encoding="utf-8"))
        self.assertEqual(states[self.a]["review_status"], "applied")
        self.assertEqual(states[self.b]["ai_judged"], True)
        self.assertEqual(states[self.a]["first_seen"], "2026-10-16T10:00:00Z")
        self.assertEqual(states[self.a]["last_seen"], "2026-10-17T10:00:00Z")

    def test_review_conflict_blocks_apply_without_changing_release(self):
        path = self.experiment / m.HISTORY
        rows = json.loads(path.read_text(encoding="utf-8"))
        rows[self.a]["review_status"] = "pending"
        path.write_text(json.dumps(rows), encoding="utf-8")
        result = self.run_migration()
        self.assertEqual(result["history_decision_conflicts_total"], 1)
        with self.assertRaisesRegex(ValueError, "conflicting human decisions"):
            self.run_migration(apply=True)
        self.assertFalse((self.release / m.HISTORY).exists())

    def test_identical_timestamp_and_different_cache_blocks(self):
        with closing(sqlite3.connect(self.experiment / m.CACHE)) as db, db:
            db.execute(
                "UPDATE validation_cache SET updated_at='2026-10-16 20:00:00'"
                " WHERE job_url='personal-fit-v1:sample:1'")
        report = self.run_migration()
        self.assertEqual(report["sqlite_ambiguous_conflicts_total"], 1)
        with self.assertRaisesRegex(ValueError, "conflicting"):
            self.run_migration(apply=True)

    def test_missing_experiment_cache_is_allowed(self):
        (self.experiment / m.CACHE).unlink()
        report = self.run_migration()
        self.assertEqual(report["sqlite_cache_records"]["experiment"], 0)
        self.assertEqual(report["sqlite_cache_records"]["combined"], 2)

    def test_invalid_history_schema_fails_before_write(self):
        (self.experiment / m.HISTORY).write_text(
            '{"not-url": {"review_status": "applied"}}', encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "Malformed history"):
            self.run_migration(apply=True)


if __name__ == "__main__":
    unittest.main()
