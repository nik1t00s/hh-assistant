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
             ("decision_policy", "exclude_words", "include_words", "exclude_companies", "exp_filter", "triage",
              "lm_reasoning_effort", "model_context")}
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


class SearchCache:
    """Independent durable queue and content-addressed extraction cache."""
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute("CREATE TABLE IF NOT EXISTS pending(scope TEXT, id TEXT, item TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(scope,id))")
        self.db.execute("CREATE TABLE IF NOT EXISTS facts(key TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS actions(url TEXT PRIMARY KEY, status TEXT NOT NULL)")
        self.db.commit()

    def enqueue(self, scope, items):
        with self.db:
            self.db.executemany("INSERT OR IGNORE INTO pending(scope,id,item) VALUES(?,?,?)",
                [(scope, i['id'], json.dumps(i, ensure_ascii=False)) for i in items])

    def pending(self, scope):
        return [json.loads(r[0]) for r in self.db.execute("SELECT item FROM pending WHERE scope=? ORDER BY created,rowid", (scope,))]

    def remove(self, scope, vid):
        with self.db:
            self.db.execute("DELETE FROM pending WHERE scope=? AND id=?", (scope, vid))

    def get_facts(self, key):
        row = self.db.execute("SELECT payload FROM facts WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_facts(self, key, payload):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO facts VALUES(?,?)", (key,json.dumps(payload,ensure_ascii=False)))

    def set_action(self, url, status):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO actions VALUES(?,?)", (url,status))

    def action(self, url):
        row=self.db.execute("SELECT status FROM actions WHERE url=?", (url,)).fetchone()
        return row[0] if row else 'Не просмотрено'

    def close(self):
        self.db.close()


def search_scope(cfg, version):
    # Source/filter changes must not revive a queue from a different search.
    keys = ('queries','role_ids','area','experience','exp_filter','remote_only',
            'remote_extra','only_with_salary','search_mode','recs_enabled',
            'hh_resume_only','resume_hash','telegram_channels','habr_enabled',
            'telegram_enabled','superjob_enabled')
    return hashlib.sha256(json.dumps([version,{k:cfg.get(k) for k in keys}],
        sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def extraction_key(source, model, prompt, schema, reasoning, context):
    return hashlib.sha256(json.dumps([source,model,prompt,schema,reasoning,context],
        sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def prioritize(items):
    """Interleave uncertain entries to avoid starving less obvious titles."""
    import re
    primary, other = [], []
    for item in items:
        target = primary if re.search(r'координатор|ассистент|проект|project|pmo|внедрен', item['name'], re.I) else other
        target.append(item)
    primary.sort(key=lambda i: i.get('experience') != 'noExperience')
    result=[]
    while primary or other:
        result.extend(primary[:4]); del primary[:4]
        result.extend(other[:1]); del other[:1]
    return result
