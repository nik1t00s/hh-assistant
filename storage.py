"""Durable local state. Personal data is never part of the source repository."""
import hashlib
import json
import os
import sqlite3
import tempfile
import time
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

    def forbidden_ids(self):
        return {r[0] for r in self.db.execute(
            "SELECT id FROM evaluations WHERE version=? AND status='incomplete' AND reason LIKE ?",
            (self.version, '%доступ запрещён (HTTP 403)%'))}

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
        self.db.execute("CREATE TABLE IF NOT EXISTS deferred(scope TEXT, id TEXT, PRIMARY KEY(scope,id))")
        self.db.execute("CREATE TABLE IF NOT EXISTS queue_migrations(scope TEXT PRIMARY KEY)")
        self.db.execute("CREATE TABLE IF NOT EXISTS facts(key TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS actions(url TEXT PRIMARY KEY, status TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS descriptions(url TEXT PRIMARY KEY, text TEXT NOT NULL, saved REAL NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS source_cursor(scope TEXT PRIMARY KEY, position INTEGER NOT NULL)")
        self.db.commit()

    def cached_description(self, url, max_age=86400):
        row = self.db.execute("SELECT text,saved FROM descriptions WHERE url=?", (url,)).fetchone()
        return row[0] if row and 0 <= time.time() - row[1] <= max_age else None

    def save_description(self, url, text):
        if text.strip():
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO descriptions VALUES(?,?,?)", (url, text, time.time()))

    def source_position(self, scope):
        row = self.db.execute("SELECT position FROM source_cursor WHERE scope=?", (scope,)).fetchone()
        return row[0] if row else 0

    def set_source_position(self, scope, position):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO source_cursor VALUES(?,?)", (scope, position))

    def enqueue(self, scope, items):
        with self.db:
            self.db.executemany("INSERT OR IGNORE INTO pending(scope,id,item) VALUES(?,?,?)",
                [(scope, i['id'], json.dumps(i, ensure_ascii=False)) for i in items])

    def pending(self, scope, include_deferred=False):
        return [json.loads(r[0]) for r in self.db.execute(
            "SELECT p.item FROM pending p WHERE p.scope=? AND (? OR NOT EXISTS "
            "(SELECT 1 FROM deferred d WHERE d.scope=p.scope AND d.id=p.id)) ORDER BY p.created,p.rowid",
            (scope, include_deferred))]

    def deferred_ids(self, scope):
        return {r[0] for r in self.db.execute("SELECT id FROM deferred WHERE scope=?", (scope,))}

    def defer(self, scope, vid):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO deferred SELECT scope,id FROM pending WHERE scope=? AND id=?", (scope, vid))

    def migrate_deferred(self, scope, ids):
        with self.db:
            if self.db.execute("SELECT 1 FROM queue_migrations WHERE scope=?", (scope,)).fetchone():
                return
            self.db.executemany("INSERT OR IGNORE INTO deferred SELECT scope,id FROM pending WHERE scope=? AND id=?", [(scope, vid) for vid in ids])
            self.db.execute("INSERT INTO queue_migrations VALUES(?)", (scope,))

    def restore_deferred(self, scope):
        count = len(self.deferred_ids(scope))
        with self.db:
            self.db.execute("DELETE FROM deferred WHERE scope=?", (scope,))
        return count

    def remove(self, scope, vid):
        with self.db:
            self.db.execute("DELETE FROM pending WHERE scope=? AND id=?", (scope, vid))
            self.db.execute("DELETE FROM deferred WHERE scope=? AND id=?", (scope, vid))

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
            'telegram_enabled','superjob_enabled','exclude_words','include_words','exclude_companies','triage')
    return hashlib.sha256(json.dumps(['queue-v2',{k:cfg.get(k) for k in keys}],
        sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def extraction_key(source, model, prompt, schema, reasoning, context):
    return hashlib.sha256(json.dumps([source,model,prompt,schema,reasoning,context],
        sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def prioritize(items, entry_first=False):
    """Interleave uncertain entries to avoid starving less obvious titles."""
    import re
    if entry_first:
        def priority(item):
            title = item.get('name', '')
            experience = item.get('experience', '')
            if experience in {'between3And6', 'moreThan6'}:
                entry = 4
            elif experience == 'noExperience' or re.search(r'стаж[её]р|стажиров|\bintern(?:ship)?\b|без\s+опыта', title, re.I):
                entry = 0
            elif experience == 'between1And3':
                entry = 3
            elif re.search(r'\bjunior\b|джун|младш|начинающ', title, re.I):
                entry = 1
            else:
                entry = 2
            technical = bool(re.search(r'support|help\s*desk|service\s*desk|поддерж|сопровожд|системн.*администратор|sysadmin|инфраструктур|it\s*operations', title, re.I))
            return entry, 0 if technical else 1
        return sorted(items, key=priority)
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


def entry_search_passes(passes):
    """Search every HH entry-level source before requesting 1–3 years."""
    regular = [(label, src) for label, src in passes if not src.get('source') and not src.get('resume')]
    rest = [(label, src) for label, src in passes if src.get('source') or src.get('resume')]
    return [(label + suffix, dict(src, experience=experience))
            for experience, suffix in [('noExperience', ' · без опыта'), ('between1And3', ' · 1–3 года')]
            for label, src in regular] + rest


def ordered_search_passes(passes, offset):
    """Rotate within experience tiers; retain original indices for the cursor."""
    indexed = list(enumerate(passes))
    rotated = indexed[offset:] + indexed[:offset]
    return sorted(rotated, key=lambda pair: 0 if pair[1][1].get('experience') == 'noExperience' else 1)
