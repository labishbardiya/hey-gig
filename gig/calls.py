"""Approval-gated single outbound calls using CALL-E Calls V2."""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
  id INTEGER PRIMARY KEY, recipient TEXT NOT NULL, phone TEXT NOT NULL,
  task TEXT NOT NULL, mode TEXT NOT NULL, request_key TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'draft', provider_id TEXT, billing_id TEXT,
  outcome TEXT, result_status TEXT, summary TEXT, transcript TEXT,
  error TEXT, next_check REAL NOT NULL DEFAULT 0, cancel_requested INTEGER NOT NULL DEFAULT 0,
  created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class CallProvider:
    def __init__(self, key, base='https://api.heycall-e.com'):
        self.key = key
        self.base = base.rstrip('/')
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, path, data=None, key=None):
        headers = {'Authorization': 'Bearer ' + self.key, 'Accept': 'application/json'}
        if data is not None:
            headers['Content-Type'] = 'application/json'
        if key:
            headers['Idempotency-Key'] = key
        request = urllib.request.Request(self.base + path, headers=headers,
                                        data=json.dumps(data).encode() if data is not None else None)
        with self.opener.open(request, timeout=10) as response:
            result = json.loads(response.read(1_000_000))
        if not isinstance(result, dict):
            raise ValueError('Invalid CALL-E response')
        return result

    def create(self, call):
        return self.request('/v2/calls', {
            'phone': call['phone'],
            'task': call['task'],
            'result_schema': {'type': 'object', 'additionalProperties': False,
                              'properties': {'summary': {'type': 'string'}}, 'required': ['summary']},
            'metadata': {'workflow_run_id': call['request_key']},
        }, call['request_key'])

    def read(self, identifier):
        return self.request('/v2/calls/' + urllib.parse.quote(identifier, safe=''))

    def cancel(self, identifier):
        return self.request('/v2/calls/' + urllib.parse.quote(identifier, safe='') + '/cancel', {})


class Calls:
    def __init__(self, library, provider=None):
        self.library = library
        key = os.environ.get('CALLE_API_KEY')
        self.provider = provider or (CallProvider(key) if key else None)
        with library.connect() as db:
            db.executescript(SCHEMA)
            db.execute("""UPDATE calls SET status='unknown', error='Submission interrupted. Check CALL-E before placing another call.'
                          WHERE status='submitting'""")

    def snapshot(self):
        with self.library.connect() as db:
            rows = db.execute('SELECT * FROM calls ORDER BY id DESC LIMIT 100').fetchall()
        return {'live_available': self.provider is not None, 'calls': [
            {k: row[k] for k in ('id', 'recipient', 'phone', 'task', 'mode', 'status',
                                 'provider_id', 'billing_id', 'outcome', 'result_status', 'summary',
                                 'transcript', 'error', 'cancel_requested')}
            for row in rows]}

    def draft(self, data):
        recipient = self.library.label(data.get('recipient'))
        task = data.get('task')
        if not isinstance(task, str) or not 1 <= len(task.strip()) <= 1500:
            raise ValueError('Enter call instructions of up to 1,500 characters.')
        mode = data.get('mode')
        if mode not in ('demo', 'live'):
            raise ValueError('Choose demo or live.')
        phone = data.get('phone') if mode == 'live' else ''
        if mode == 'live' and not self.provider:
            raise ValueError('Live CALL-E is unavailable. Use Demo or configure the Mac backend.')
        if mode == 'live' and (not isinstance(phone, str) or not re.fullmatch(r'\+[1-9][0-9]{7,14}', phone)):
            raise ValueError('Use an international number, including the + and country code.')
        with self.library.connect() as db:
            identifier = db.execute(
                'INSERT INTO calls (recipient, phone, task, mode, request_key) VALUES (?, ?, ?, ?, ?)',
                (recipient, phone, task.strip(), mode, uuid.uuid4().hex)).lastrowid
            self.library.event(db, f'Call {identifier}: draft awaiting approval ({mode})')

    def act(self, data):
        identifier, action = data.get('id'), data.get('action')
        if type(identifier) is not int or not 1 <= identifier < 2**63:
            raise ValueError('Invalid call ID.')
        with self.library.connect() as db:
            if action in ('approve', 'deny'):
                state = 'queued' if action == 'approve' else 'denied'
                row = db.execute("""UPDATE calls SET status=? WHERE id=? AND status='draft'
                    AND (mode='demo' OR ? OR ?='deny') RETURNING id""",
                    (state, identifier, int(self.provider is not None), action)).fetchone()
            elif action == 'cancel':
                cursor = db.execute("""UPDATE calls SET status='cancelled'
                    WHERE id=? AND status='queued' AND provider_id IS NULL RETURNING id""", (identifier,))
                row = cursor.fetchone()
                if row is None:
                    state = 'cancellation requested'
                    row = db.execute("""UPDATE calls SET cancel_requested=1, next_check=0
                        WHERE id=? AND provider_id IS NOT NULL AND cancel_requested=0 AND result_status='pending'
                        AND status NOT IN ('completed','failed','cancelled') AND (mode='demo' OR ?)
                        RETURNING id""", (identifier, int(self.provider is not None))).fetchone()
                else:
                    state = 'cancelled'
            else:
                raise ValueError('Unknown call action.')
            if row is None:
                raise ValueError('That action is no longer available for this call.')
            self.library.event(db, f'Call {identifier}: {state}')

    def step(self, now=None):
        now = time.time() if now is None else now
        with self.library.connect() as db:
            row = db.execute("""SELECT * FROM calls WHERE next_check<=?
                AND (mode='demo' OR ?) AND ((status='queued' AND provider_id IS NULL) OR
                (provider_id IS NOT NULL AND (result_status='pending' OR cancel_requested=1)))
                ORDER BY (status='queued') DESC, next_check, id LIMIT 1""",
                (now, int(self.provider is not None))).fetchone()
            if row is None:
                return
            if row['status'] == 'queued' and row['provider_id'] is None:
                claimed = db.execute("UPDATE calls SET status='submitting' WHERE id=? AND status='queued' AND provider_id IS NULL",
                                     (row['id'],)).rowcount
                if not claimed:
                    return
        creating = row['status'] == 'queued' and row['provider_id'] is None
        cancelling = bool(row['cancel_requested'])
        try:
            if row['mode'] == 'demo':
                result = self.simulate(row)
            elif creating:
                result = self.provider.create(row)
            elif cancelling:
                self.provider.cancel(row['provider_id'])
                result = self.provider.read(row['provider_id'])
            else:
                result = self.provider.read(row['provider_id'])
            identifier = result.get('id') if creating else row['provider_id']
            if not isinstance(identifier, str) or not identifier:
                raise ValueError('CALL-E did not return a resource ID')
            self.save_result(row, identifier, result, now)
        except (OSError, ValueError, TypeError) as error:
            code = getattr(error, 'code', None)
            definitive = code in (400, 401, 402, 403, 422)
            status = ('failed' if definitive else 'unknown') if creating else row['status']
            if creating:
                message = (f'CALL-E rejected the submission (HTTP {code}).' if definitive else
                           'Submission could not be confirmed. Check CALL-E before placing another call.')
            elif cancelling:
                message = 'Cancellation could not be confirmed. Check the current call status.'
            else:
                message = 'Status check failed. The backend will retry.'
            with self.library.connect() as db:
                db.execute('UPDATE calls SET status=?, error=?, next_check=?, cancel_requested=0 WHERE id=?',
                           (status, message, now + 15, row['id']))
                if creating or cancelling:
                    self.library.event(db, f'Call {row["id"]}: {message}')

    @staticmethod
    def simulate(row):
        if row['cancel_requested']:
            return {'status': 'cancelled', 'result_status': 'not_applicable'}
        if row['status'] == 'queued' and row['provider_id'] is None:
            return {'id': 'demo-' + row['request_key'], 'status': 'accepted', 'result_status': 'pending'}
        if row['status'] == 'accepted':
            return {'status': 'in_progress', 'result_status': 'pending'}
        return {'status': 'completed', 'call_outcome': 'completed', 'result_status': 'available',
                'result': {'summary': 'Demo completed. No telephone call was placed.'},
                'transcript': [{'speaker': 'assistant', 'text': 'This is a simulated call.'}]}

    def save_result(self, row, identifier, result, now):
        status = str(result.get('status') or row['status'])[:80]
        ready = str(result.get('result_status') or 'pending')[:80]
        fields = result.get('result')
        summary = str(fields.get('summary') or '')[:4000] if isinstance(fields, dict) else None
        transcript = result.get('transcript')
        lines = []
        if isinstance(transcript, list):
            for entry in transcript[:150]:
                if isinstance(entry, dict):
                    lines.append(f'{str(entry.get("speaker", ""))[:40]}: {str(entry.get("text", ""))[:2000]}')
        delay = 8 if row['mode'] == 'live' else 4
        with self.library.connect() as db:
            db.execute("""UPDATE calls SET provider_id=?, billing_id=?, status=?, outcome=?, result_status=?,
                summary=?, transcript=?, error=?,
                cancel_requested=CASE WHEN ? OR ? != 'pending' THEN 0 ELSE cancel_requested END,
                next_check=? WHERE id=?""",
                (identifier, str(result['call_id'])[:200] if result.get('call_id') else row['billing_id'],
                 status, str(result['call_outcome'])[:80] if result.get('call_outcome') else None, ready,
                 summary, '\n'.join(lines) or None, 'CALL-E reported an error.' if result.get('error') else None,
                 row['cancel_requested'], ready, now + delay, row['id']))
            if status != row['status'] or ready != row['result_status']:
                self.library.event(db, f'Call {row["id"]}: {status} ({ready})')
