"""Local documents, activity and share approvals."""
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
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
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL, due TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'scheduled'
);
CREATE TABLE IF NOT EXISTS routines (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, action TEXT NOT NULL
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
                'reminders': [dict(row) for row in db.execute(
                    "SELECT * FROM reminders WHERE state != 'cancelled' ORDER BY due LIMIT 100")],
                'routines': [dict(row) for row in db.execute('SELECT * FROM routines ORDER BY id LIMIT 100')],
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

    def add_reminder(self, title, due):
        title = self.label(title)
        if not isinstance(due, str):
            raise ValueError('Choose a date and time.')
        timestamp = datetime.fromisoformat(due)
        if timestamp.utcoffset() is None or timestamp <= datetime.now(timezone.utc):
            raise ValueError('Choose a future date and time with a timezone.')
        with self.connect() as db:
            db.execute('INSERT INTO reminders (title, due) VALUES (?, ?)',
                       (title, timestamp.astimezone(timezone.utc).isoformat()))
            self.event(db, f'Reminder scheduled: {title}')

    def cancel_reminder(self, identifier):
        with self.connect() as db:
            row = db.execute("UPDATE reminders SET state = 'cancelled' WHERE id = ? AND state = 'scheduled' RETURNING title",
                             (identifier,)).fetchone()
            if row is None:
                raise ValueError('Only scheduled reminders can be cancelled.')
            self.event(db, f'Reminder cancelled: {row["title"]}')

    def deliver_reminders(self):
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            due = db.execute("UPDATE reminders SET state = 'due' WHERE state = 'scheduled' AND due <= ? RETURNING title",
                             (now,)).fetchall()
            for row in due:
                self.event(db, f'Reminder due: {row["title"]}')

    @staticmethod
    def label(value):
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 200:
            raise ValueError('Enter a name of up to 200 characters.')
        return value.strip()

    def add_routine(self, name, action):
        name = self.label(name)
        if action not in ('scan', 'privacy'):
            raise ValueError('Choose an available local action.')
        with self.connect() as db:
            db.execute('INSERT INTO routines (name, action) VALUES (?, ?)', (name, action))
            self.event(db, f'Routine saved: {name}')

    def run_routine(self, identifier):
        with self.connect() as db:
            row = db.execute('SELECT name, action FROM routines WHERE id = ?', (identifier,)).fetchone()
            if row is None:
                raise ValueError('Routine does not exist.')
            self.event(db, f'Ran routine: {row["name"]}')
            return row['action']
