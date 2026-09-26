"""Durable local state. Personal data is never part of the source repository."""
import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager


@contextmanager
def atomic_text(path, encoding="utf-8", newline=None):
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline=newline) as stream:
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, data):
    with atomic_text(path) as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8-sig") as stream:
            return json.load(stream)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Не удалось прочитать {os.path.basename(path)}. "
                           "Файл сохранён без изменений; восстановите его из копии.") from exc


def evaluation_fingerprint(profile, cfg, model, fast_model, prompts):
    # Bump this version when parser or deterministic filtering semantics change.
    rules = {key: cfg.get(key) for key in
             ("exclude_words", "include_words", "exclude_companies", "exp_filter", "triage")}
    payload = [2, profile, rules, model, fast_model, prompts]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False,
                                    sort_keys=True).encode()).hexdigest()


class EvaluationStore:
    """Failed/incomplete rows remain retryable on the next run.

    Legacy seen_ids.json is deliberately not imported: it contains no status
    or rule version, so importing it would preserve the old false exclusions.
    """
    def __init__(self, path, version):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.version = version
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute("""CREATE TABLE IF NOT EXISTS evaluations (
            id TEXT NOT NULL, version TEXT NOT NULL, status TEXT NOT NULL,
            reason TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(id, version))""")
        self.db.commit()

    def completed_ids(self):
        return {row[0] for row in self.db.execute(
            "SELECT id FROM evaluations WHERE version=? AND status IN ('evaluated','skipped')",
            (self.version,))}

    def mark(self, vid, status, reason):
        if status not in {"evaluated", "skipped", "failed", "incomplete"}:
            raise ValueError("Unknown evaluation status")
        with self.db:
            self.db.execute("""INSERT INTO evaluations(id,version,status,reason)
                VALUES (?,?,?,?) ON CONFLICT(id,version) DO UPDATE SET
                status=excluded.status, reason=excluded.reason,
                updated_at=CURRENT_TIMESTAMP""", (vid, self.version, status, str(reason)))

    def close(self):
        self.db.close()
