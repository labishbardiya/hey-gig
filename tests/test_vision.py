import base64
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from gig.vision import VisionUnavailable, answer_frame


JPEG = b'\xff\xd8test frame\xff\xd9'


class VisionTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.status = 200
        self.result = b'{"choices":[{"message":{"content":"A red mug."}}]}'
        test = self

        class Model(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = self.rfile.read(int(self.headers['Content-Length']))
                test.requests.append((self.path, json.loads(payload)))
                self.send_response(test.status)
                self.send_header('Location', 'https://example.invalid/redirect')
                self.end_headers()
                self.wfile.write(test.result)

            def log_message(self, *_):
                pass

        self.server = HTTPServer(('127.0.0.1', 0), Model)
        self.addCleanup(self.server.server_close)
        self.worker = threading.Thread(target=self.server.serve_forever)
        self.worker.start()
        self.addCleanup(self.worker.join)
        self.addCleanup(self.server.shutdown)

    def test_single_jpeg_and_question_sent_to_local_model(self):
        self.assertEqual(answer_frame(JPEG, ' What is this? ', port=self.server.server_port), 'A red mug.')
        path, payload = self.requests[0]
        self.assertEqual(path, '/v1/chat/completions')
        text, image = payload['messages'][1]['content']
        self.assertEqual(text['text'], 'What is this?')
        prefix, encoded = image['image_url']['url'].split(',')
        self.assertEqual(prefix, 'data:image/jpeg;base64')
        self.assertEqual(base64.b64decode(encoded), JPEG)

    def test_invalid_inputs_do_not_reach_model(self):
        for image, question in [(b'not a jpeg', 'What is this?'), (JPEG, '  '), (JPEG, 'x' * 501)]:
            with self.assertRaises(ValueError):
                answer_frame(image, question, port=self.server.server_port)
        self.assertEqual(self.requests, [])

    def test_redirect_is_rejected(self):
        self.status = 307
        with self.assertRaises(VisionUnavailable):
            answer_frame(JPEG, 'What is this?', port=self.server.server_port)
        self.assertEqual(len(self.requests), 1)
