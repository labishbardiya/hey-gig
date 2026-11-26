"""Local documents, activity and share approvals."""
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY, pages INTEGER NOT NULL, pdf BLOB NOT NULL,
    created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id),
    recipient TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY, message TEXT NOT NULL,
    created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class Library:
    def __init__(self, path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.touch(mode=0o600, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys = ON')
            yield db

    def add_document(self, pdf, pages):
        with self.connect() as db:
            document = db.execute('INSERT INTO documents (pages, pdf) VALUES (?, ?)', (pages, pdf)).lastrowid
            self.event(db, f'Saved document {document} with {pages} pages')
            return document

    def document(self, document_id):
        with self.connect() as db:
            row = db.execute('SELECT pdf FROM documents WHERE id = ?', (document_id,)).fetchone()
            return row['pdf'] if row else None

    def snapshot(self):
        with self.connect() as db:
            return {
                'documents': [dict(row) for row in db.execute(
                    'SELECT id, pages, created FROM documents ORDER BY id DESC LIMIT 100')],
                'approvals': [dict(row) for row in db.execute(
                    "SELECT * FROM approvals ORDER BY (state = 'pending') DESC, id DESC LIMIT 100")],
                'activity': [dict(row) for row in db.execute(
                    'SELECT * FROM activity ORDER BY id DESC LIMIT 100')],
            }

    @staticmethod
    def event(db, message):
        db.execute('INSERT INTO activity (message) VALUES (?)', (message,))

    def request_share(self, document_id, recipient):
        if type(document_id) is not int or not isinstance(recipient, str) or not 1 <= len(recipient.strip()) <= 200:
            raise ValueError('Choose a document and enter a recipient of up to 200 characters.')
        with self.connect() as db:
            try:
                approval = db.execute('INSERT INTO approvals (document_id, recipient) VALUES (?, ?)',
                                      (document_id, recipient.strip())).lastrowid
            except sqlite3.IntegrityError as exc:
                raise ValueError('Document does not exist.') from exc
            self.event(db, f'Requested approval {approval} for document {document_id}')

    def decide(self, approval_id, decision):
        if type(approval_id) is not int or decision not in ('approved', 'denied'):
            raise ValueError('Choose Approve or Deny.')
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE approvals SET state = ? WHERE id = ? AND state = 'pending'",
                (decision, approval_id),
            )
            if not cursor.rowcount:
                raise ValueError('This request is no longer pending.')
            self.event(db, f'Share request {approval_id} {decision}')
