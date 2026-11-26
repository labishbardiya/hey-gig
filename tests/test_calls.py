import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from gig.calls import Calls, CallProvider
from gig.library import Library


class CallTests(unittest.TestCase):
    def test_v2_contract_approval_and_status_after_restart(self):
        requests = []

        class Provider(BaseHTTPRequestHandler):
            def reply(self, code, result):
                body = json.dumps(result).encode()
                self.send_response(code)
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append((self.path, self.headers['Authorization'], self.headers['Idempotency-Key'], payload))
                self.reply(202, {'id': 'call_local_sample', 'status': 'accepted', 'result_status': 'pending'})

            def do_GET(self):
                requests.append(self.path)
                self.reply(200, {'id': 'call_local_sample', 'call_id': 'billing_sample',
                                 'status': 'completed', 'call_outcome': 'busy',
                                 'result_status': 'unavailable', 'transcript': []})

            def log_message(self, *_):
                pass

        mock = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        thread = threading.Thread(target=mock.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(mock.server_close)
        self.addCleanup(mock.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            library = Library(Path(tmp) / 'library.sqlite3')
            client = CallProvider('fixture-key', f'http://127.0.0.1:{mock.server_port}')
            calls = Calls(library, client)
            draft = {'mode': 'live', 'recipient': 'Fixture', 'phone': '+12025550123', 'task': 'Say hello'}
            calls.draft(draft)
            calls.step(now=1)
            self.assertEqual(requests, [])
            calls.act({'id': 1, 'action': 'approve'})
            with self.assertRaises(ValueError):
                calls.act({'id': 1, 'action': 'approve'})
            calls.step(now=2)
            route, auth, key, payload = requests[0]
            self.assertEqual((route, auth, payload['phone'], payload['task']),
                             ('/v2/calls', 'Bearer fixture-key', draft['phone'], draft['task']))
            self.assertEqual(key, payload['metadata']['workflow_run_id'])
            self.assertFalse(payload['result_schema']['additionalProperties'])
            calls = Calls(library, client)
            calls.step(now=20)
            calls.step(now=40)
            self.assertEqual(len(requests), 2)
            self.assertEqual(requests[1], '/v2/calls/call_local_sample')
            call, = calls.snapshot()['calls']
            self.assertEqual((call['status'], call['outcome'], call['billing_id']),
                             ('completed', 'busy', 'billing_sample'))

    def test_demo_deny_cancel_and_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = Calls(Library(Path(tmp) / 'library.sqlite3'))
            for _ in range(3):
                calls.draft({'mode': 'demo', 'recipient': 'Test', 'task': 'Ask about office hours'})
            calls.act({'id': 1, 'action': 'deny'})
            calls.act({'id': 2, 'action': 'approve'})
            calls.act({'id': 2, 'action': 'cancel'})
            calls.act({'id': 3, 'action': 'approve'})
            for now in (1, 5, 9):
                calls.step(now=now)
            self.assertEqual([row['status'] for row in calls.snapshot()['calls']],
                             ['completed', 'cancelled', 'denied'])
            self.assertIn('simulated', calls.snapshot()['calls'][0]['transcript'])
