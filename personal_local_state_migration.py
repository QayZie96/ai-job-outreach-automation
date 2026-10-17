"""Safely consolidate local Personal RAY state without network or API calls.

Dry run by default. Sources are the two existing PC worktrees; the target is
the current release worktree. Never mutate source histories or databases.

Usage:
  python personal_local_state_migration.py
  python personal_local_state_migration.py --apply

No credentials, job URLs, CVs, Gemini assessments, or private profile data
are printed. Any ambiguity in explicit review decisions fails closed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing, nullcontext
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile


ROOT = Path(__file__).resolve().parent
HISTORY = "personal_discovery_history.local.json"
CACHE = "validation_cache.db"
CACHE_SCHEMA = """CREATE TABLE IF NOT EXISTS validation_cache (
    job_url TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
    result_json TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)"""
CACHE_FIELDS = "job_url, fingerprint, result_json, updated_at"
REVIEW_DONE = {"reviewed", "dismissed", "applied"}


def _stamp(value):
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _fingerprint(key):
    return hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:12]


def _read_history(file):
    if not file.exists():
        return {}
    value = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"History is not a URL-keyed JSON object: {file.name}")
    for key, rec in value.items():
        if not isinstance(key, str) or not key.startswith(("https://", "http://")) or not isinstance(rec, dict):
            raise ValueError("Malformed history URL key or record (no changes made)")
    return value


def combine_histories(sources, *, reconcile_ai_judged=False):
    """Merge observations, preserving user decisions and confirmed AI reviews.

    Without opt-in, contradictory AI flags are shown as conflicts. When the
    user explicitly opts in, preserve a documented prior AI assessment
    (ai_judged=True with a valid ai_judged_at), but NEVER override conflicting
    human review statuses or an undocumented AI state.
    """
    merged = {}
    source_sizes = {}
    conflicts = {"review_status": set(), "ai_judged": set(),
                 "undated_metadata": set()}
    ai_reconciled = set()
    for source_name, file in sources:
        rows = _read_history(file)
        source_sizes[source_name] = len(rows)
        for url, incoming in rows.items():
            if url not in merged:
                merged[url] = dict(incoming)
                continue
            prior = merged[url]
            p_state = str(prior.get("review_status") or "pending").lower()
            i_state = str(incoming.get("review_status") or "pending").lower()
            if p_state != i_state:
                # Human decisions are never reconciled automatically.
                conflicts["review_status"].add(url)
                continue
            ai_mismatch = bool(prior.get("ai_judged")) != bool(incoming.get("ai_judged"))
            if ai_mismatch:
                documented = (prior if prior.get("ai_judged") else incoming)
                # Valid ai_judged_at is an explicit completed-review signal.
                # Preserving it avoids repeating paid evaluation of historic
                # scored vacancies. This is an opt-in reconciliation, since a
                # separate pending reset cannot be inferred from timestamps.
                if (not reconcile_ai_judged or
                        not _stamp(documented.get("ai_judged_at"))):
                    conflicts["ai_judged"].add(url)
                    continue
                ai_reconciled.add(url)
            p_at, i_at = _stamp(prior.get("last_seen")), _stamp(incoming.get("last_seen"))
            if p_at is None and i_at is None:
                # Same URL and no provable ordering. Preserve all existing
                # metadata without trying to guess which record is newer.
                if prior != incoming:
                    conflicts["undated_metadata"].add(url)
                continue
            newer = incoming if (i_at and (not p_at or i_at > p_at)) else prior
            older = prior if newer is incoming else incoming
            result = {**older, **newer}
            if ai_mismatch:
                documented = prior if prior.get("ai_judged") else incoming
                result["ai_judged"] = True
                result["ai_judged_at"] = documented["ai_judged_at"]
                result["content_updated_since_review"] = bool(
                    prior.get("content_updated_since_review") or
                    incoming.get("content_updated_since_review")
                )
            times = [(_stamp(r.get("first_seen")), r.get("first_seen"))
                     for r in (prior, incoming)]
            times = [x for x in times if x[0]]
            if times:
                result["first_seen"] = min(times)[1]
            if p_at or i_at:
                result["last_seen"] = max(
                    [(date, date_str) for date, date_str in (
                        (p_at, prior.get("last_seen")),
                        (i_at, incoming.get("last_seen")),
                    ) if date]
                )[1]
            merged[url] = result
    unresolved = set().union(*conflicts.values())
    return (
        merged, source_sizes,
        sorted(_fingerprint(u) for u in unresolved),
        {k: len(v) for k, v in conflicts.items()},
        len(ai_reconciled),
    )


def _source_connection(file):
    if not file.exists():
        return None
    return sqlite3.connect(file.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)


def _cache_rows(conn):
    if conn is None:
        return {}
    exists = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='validation_cache'").fetchone()[0]
    if not exists:
        raise ValueError("Database is missing validation_cache table")
    rows = conn.execute(f"SELECT {CACHE_FIELDS} FROM validation_cache").fetchall()
    result = {}
    for row in rows:
        if not isinstance(row[0], str) or not isinstance(row[1], str):
            raise ValueError("Malformed cache key/fingerprint")
        json.loads(row[2])
        result[row[0]] = row
    return result


def _copy_database(source, target):
    conn = _source_connection(source)
    if conn is None:
        raise FileNotFoundError("Production cache database missing")
    with closing(conn):
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Production cache failed integrity check")
        with closing(sqlite3.connect(target)) as dst:
            conn.backup(dst)


def _prepare_cache(production, experiment, release, scratch):
    # Starting with a complete SQLite backup preserves any other original
    # tables, including ordinary non-personal RAY cache entries.
    stage = scratch / CACHE
    _copy_database(production / CACHE, stage)
    with closing(sqlite3.connect(stage)) as dest:
        dest.execute(CACHE_SCHEMA)
        merged = _cache_rows(dest)
        counts = {"production": len(merged)}
        collisions = 0
        unresolved = set()
        for label, path in (("experiment", experiment), ("release", release)):
            source_conn = _source_connection(path / CACHE)
            with (closing(source_conn) if source_conn is not None else nullcontext(None)) as conn:
                if conn and conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError(f"{label} cache failed integrity check")
                rows = _cache_rows(conn)
            counts[label] = len(rows)
            for key, row in rows.items():
                old = merged.get(key)
                if old is not None:
                    if old[:3] != row[:3]:
                        collisions += 1
                        old_at, new_at = _stamp(old[3]), _stamp(row[3])
                        if old_at == new_at or (not old_at and not new_at):
                            unresolved.add(key)
                            continue
                        if old_at and (not new_at or old_at > new_at):
                            continue
                    else:
                        # Preserve existing content if identical.
                        continue
                dest.execute(
                    """INSERT INTO validation_cache (job_url, fingerprint, result_json, updated_at)
                       VALUES (?, ?, ?, ?) ON CONFLICT(job_url) DO UPDATE SET
                       fingerprint=excluded.fingerprint, result_json=excluded.result_json,
                       updated_at=excluded.updated_at""",
                    row,
                )
                merged[key] = row
        dest.commit()
        if dest.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Merged cache failed integrity check")
        counts["combined"] = len(_cache_rows(dest))
        counts["conflicting_keys_with_distinct_payloads"] = collisions
        return stage, counts, sorted(_fingerprint(key) for key in unresolved)


def _default_backup():
    return Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "PersonalRay" / (
        "state-backup-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    )


def migrate(*, production, experiment, release, apply=False, backup_dir=None,
            reconcile_ai_judged=False):
    production, experiment, release = map(Path, (production, experiment, release))
    if len({p.resolve() for p in (production, experiment, release)}) != 3:
        raise ValueError("Production, experiment and release must be separate directories")
    for directory in (production, experiment, release):
        if not directory.is_dir():
            raise FileNotFoundError(f"Missing local worktree: {directory}")

    histories = [
        ("production", production / HISTORY),
        ("experiment", experiment / HISTORY),
        ("release", release / HISTORY),
    ]
    rows, hist_counts, history_conflicts, conflict_reasons, ai_reconciled = (
        combine_histories(histories, reconcile_ai_judged=reconcile_ai_judged)
    )

    with tempfile.TemporaryDirectory(prefix="ray-state-audit-") as work:
        merged_db, cache_counts, cache_conflicts = _prepare_cache(
            production, experiment, release, Path(work)
        )
        conflicts = history_conflicts + cache_conflicts
        summary = {
            "mode": "apply" if apply else "dry_run",
            "history_records_by_source": hist_counts,
            "history_union": len(rows),
            "history_decision_conflict_ids": history_conflicts[:20],
            "history_decision_conflicts_total": len(history_conflicts),
            "history_conflicts_by_reason": conflict_reasons,
            "ai_judgments_reconciled": ai_reconciled,
            "ai_reconciliation_opt_in": reconcile_ai_judged,
            "sqlite_cache_records": cache_counts,
            "sqlite_ambiguous_conflict_ids": cache_conflicts[:20],
            "sqlite_ambiguous_conflicts_total": len(cache_conflicts),
            "sources_modified": False,
            "gemini_calls": 0,
            "provider_calls": 0,
            "sheet_writes": 0,
        }
        if not apply:
            return summary
        if conflicts:
            raise ValueError(
                "Cannot apply: conflicting human decisions/cache timestamps. "
                "Resolve using the dry-run hashed conflict IDs."
            )
        if (release / HISTORY).exists():
            current = _read_history(release / HISTORY)
            if current != _read_history(release / HISTORY):
                raise RuntimeError("Release history changed during migration")
        if backup_dir is None:
            backup_dir = _default_backup()
        backup_dir = Path(backup_dir)
        if backup_dir.exists():
            raise FileExistsError("Backup directory already exists; choose a fresh location")
        backup_dir.mkdir(parents=True)
        for filename in (HISTORY, CACHE):
            current = release / filename
            if current.exists():
                if filename == CACHE:
                    _copy_database(current, backup_dir / CACHE)
                else:
                    shutil.copy2(current, backup_dir / HISTORY)
        # Make the new artifacts, then replace only the release targets.
        staged_history = release / "personal_discovery_history.migration.tmp.json"
        staged_db = release / "validation_cache.migration.tmp.db"
        try:
            staged_history.write_text(
                json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            shutil.copy2(merged_db, staged_db)
            if _read_history(staged_history) != rows:
                raise ValueError("Staged history verification failed")
            with closing(sqlite3.connect(staged_db)) as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Staged SQLite verification failed")
            os.replace(staged_history, release / HISTORY)
            os.replace(staged_db, release / CACHE)
        finally:
            staged_history.unlink(missing_ok=True)
            staged_db.unlink(missing_ok=True)
        summary["backup_dir"] = str(backup_dir)
        summary["release_written"] = True
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    base = ROOT.parent
    parser.add_argument("--production", type=Path, default=base / "ray-personal-job-discovery")
    parser.add_argument("--experiment", type=Path, default=base / "ray-provider-audit")
    parser.add_argument("--release", type=Path, default=ROOT)
    parser.add_argument("--apply", action="store_true",
                        help="Copy merged history/cache only into release, with backup")
    parser.add_argument("--reconcile-ai-judged", action="store_true",
                        help="Opt in to preserving documented completed AI reviews across history copies; still blocks human decision conflicts")
    parser.add_argument("--backup-dir", type=Path, help="Unique private backup folder (apply only)")
    args = parser.parse_args()
    result = migrate(
        production=args.production, experiment=args.experiment,
        release=args.release, apply=args.apply, backup_dir=args.backup_dir,
        reconcile_ai_judged=args.reconcile_ai_judged,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
