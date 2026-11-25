"""Persistent, owner-scoped drafts and immutable revision snapshots."""
import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.domain import Submission

DATA_ROOT = Path(os.getenv('SCRUTINY_DATA_DIR', Path(__file__).resolve().parents[1] / 'data'))


class Conflict(Exception):
    pass


class Repository:
    def __init__(self, root: Path = DATA_ROOT):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / 'scrutiny.sqlite3'
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY, owner TEXT NOT NULL, revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions(id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL, audit TEXT, created TEXT NOT NULL, PRIMARY KEY(id,revision));
                CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL, suffix TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL, text TEXT NOT NULL, pages TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=15)
        db.execute('PRAGMA foreign_keys = ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def owner(key):
        return hashlib.sha256(key.encode()).hexdigest()

    def create(self, owner, payload: Submission):
        rid = uuid.uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO drafts VALUES(?,?,1)', (rid, self.owner(owner)))
            db.execute('INSERT INTO revisions VALUES(?,1,?,NULL,?)', (rid, payload.model_dump_json(), datetime.now(timezone.utc).isoformat()))
        return self.get(owner, rid)

    def get(self, owner, rid, revision=None):
        with self.connect() as db:
            draft = db.execute('SELECT revision FROM drafts WHERE id=? AND owner=?', (rid, self.owner(owner))).fetchone()
            if not draft:
                raise KeyError(rid)
            rev = revision if revision is not None else draft[0]
            row = db.execute('SELECT payload,audit,created FROM revisions WHERE id=? AND revision=?', (rid, rev)).fetchone()
            if not row:
                raise KeyError(rid)
            return {'id': rid, 'revision': rev, 'latest_revision': draft[0], 'submission': json.loads(row[0]), 'audit': json.loads(row[1]) if row[1] else None, 'created_at': row[2]}

    def update(self, owner, rid, expected, payload, *, audit=None, expected_audit=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision FROM drafts WHERE id=? AND owner=?', (rid, self.owner(owner))).fetchone()
            if not row:
                raise KeyError(rid)
            if expected != row[0]:
                raise Conflict('This draft was changed in another window. Reload before saving.')
            if expected_audit is not None:
                previous = db.execute('SELECT audit FROM revisions WHERE id=? AND revision=?', (rid, expected)).fetchone()
                if not previous or not previous[0] or json.loads(previous[0]) != expected_audit:
                    raise Conflict('The AI findings changed while you were reviewing them. Reload and check the recommendation again.')
            rev = expected + 1
            db.execute('INSERT INTO revisions VALUES(?,?,?,?,?)',
                       (rid, rev, payload.model_dump_json(), json.dumps(audit) if audit is not None else None,
                        datetime.now(timezone.utc).isoformat()))
            db.execute('UPDATE drafts SET revision=? WHERE id=?', (rev, rid))
        return self.get(owner, rid, rev)

    def save_audit(self, owner, rid, revision, audit):
        self.get(owner, rid, revision)
        with self.connect() as db:
            # Each immutable source revision owns its own audit; no global latest report.
            db.execute('UPDATE revisions SET audit=? WHERE id=? AND revision=?', (json.dumps(audit), rid, revision))

    def save_document(self, owner, doc_id, name, suffix, content, text, pages):
        with self.connect() as db:
            db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?)', (doc_id, self.owner(owner), name, suffix, hashlib.sha256(content).hexdigest(), len(content), text, json.dumps(pages)))

    def document(self, owner, doc_id):
        with self.connect() as db:
            row = db.execute('SELECT name,suffix,sha256,size,text,pages FROM documents WHERE id=? AND owner=?', (doc_id, self.owner(owner))).fetchone()
            if not row:
                raise KeyError(doc_id)
            return dict(zip(('name','suffix','sha256','size','text','pages'), (*row[:5], json.loads(row[5]))))

    def list_drafts(self,owner):
        with self.connect() as db:
            rows=db.execute('SELECT r.id,r.revision,r.payload,r.created FROM drafts d JOIN revisions r ON d.id=r.id AND d.revision=r.revision WHERE d.owner=? ORDER BY r.created DESC',(self.owner(owner),)).fetchall()
            return [{'id':rid,'revision':revision,'title':json.loads(payload)['title'],'created_at':created} for rid,revision,payload,created in rows]
