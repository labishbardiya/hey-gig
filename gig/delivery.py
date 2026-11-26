"""Approval-gated delivery of saved documents."""
import sqlite3

from gig.drive import drive_access_token, upload_pdf
from gig.messaging import send_telegram, telegram_configured, validate_chat_id, validate_whatsapp_phone, whatsapp_url

SCHEMA = """
CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    channel TEXT NOT NULL,
    recipient TEXT NOT NULL,
    source_link TEXT,
    state TEXT NOT NULL DEFAULT 'pending',
    result TEXT,
    created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class Deliveries:
    def __init__(self, library):
        self.library = library
        with library.connect() as db:
            db.executescript(SCHEMA)
            db.execute("UPDATE deliveries SET state='unknown', result=? WHERE state='sending'",
                       ('Submission interrupted. Check the provider before making a new draft.',))

    def snapshot(self):
        with self.library.connect() as db:
            return [dict(row) for row in db.execute(
                'SELECT * FROM deliveries ORDER BY id DESC LIMIT 100')]

    def draft(self, data):
        channel = data.get('channel')
        document = data.get('document')
        if type(document) is not int or not 1 <= document < 2**63:
            raise ValueError('Choose a saved document.')
        if channel == 'drive':
            if not drive_access_token():
                raise ValueError('Configure Google Drive on the Mac first.')
            recipient = 'Configured Google Drive account'
        elif channel == 'telegram':
            if not telegram_configured():
                raise ValueError('Configure a Telegram bot on the Mac first.')
            recipient = validate_chat_id(data.get('recipient'))
        elif channel == 'whatsapp':
            recipient = validate_whatsapp_phone(data.get('recipient'))
        else:
            raise ValueError('Choose Drive, Telegram or WhatsApp.')
        with self.library.connect() as db:
            source_link = None
            if channel == 'whatsapp':
                row = db.execute("""SELECT result FROM deliveries
                    WHERE document_id=? AND channel='drive' AND state='delivered'
                    ORDER BY id DESC LIMIT 1""", (document,)).fetchone()
                if not row:
                    raise ValueError('Upload this document to Drive first. WhatsApp shares its link.')
                source_link = row['result']
            try:
                identifier = db.execute(
                    'INSERT INTO deliveries (document_id, channel, recipient, source_link) VALUES (?, ?, ?, ?)',
                    (document, channel, recipient, source_link)).lastrowid
            except sqlite3.IntegrityError as error:
                raise ValueError('Document does not exist.') from error
            self.library.event(db, f'Delivery {identifier}: {channel} draft awaiting approval')

    def decide(self, data):
        identifier, decision = data.get('id'), data.get('decision')
        if type(identifier) is not int or not 1 <= identifier < 2**63 or decision not in ('approve', 'deny'):
            raise ValueError('Choose an approval and a decision.')
        state = 'queued' if decision == 'approve' else 'denied'
        with self.library.connect() as db:
            count = db.execute("UPDATE deliveries SET state=? WHERE id=? AND state='pending'",
                               (state, identifier)).rowcount
            if not count:
                raise ValueError('This approval is no longer pending.')
            self.library.event(db, f'Delivery {identifier}: {state}')

    def step(self):
        with self.library.connect() as db:
            row = db.execute("""UPDATE deliveries SET state='sending'
                WHERE id=(SELECT id FROM deliveries WHERE state='queued' ORDER BY id LIMIT 1)
                RETURNING *""").fetchone()
        if not row:
            return
        state = 'delivered'
        try:
            document = row['document_id']
            filename = f'hey-gig-{document}.pdf'
            if row['channel'] == 'whatsapp':
                result = whatsapp_url(row['recipient'], f'Hey GIG scan {document}: {row["source_link"]}')
                state = 'handoff'
            else:
                pdf = self.library.document(document)
                if pdf is None:
                    raise ValueError('The document is unavailable.')
                if row['channel'] == 'drive':
                    result = upload_pdf(pdf, filename)
                else:
                    result = send_telegram(pdf, filename, row['recipient'])
        except (ValueError, OSError) as error:
            if getattr(error, 'uncertain', isinstance(error, OSError)):
                state = 'unknown'
                result = 'Delivery could not be confirmed. Check the provider before creating another draft.'
            else:
                state = 'failed'
                result = 'Delivery failed. Check the provider credentials, destination, and permissions.'
        with self.library.connect() as db:
            db.execute('UPDATE deliveries SET state=?, result=? WHERE id=?', (state, result, row['id']))
            self.library.event(db, f'Delivery {row["id"]}: {row["channel"]} {state}')
