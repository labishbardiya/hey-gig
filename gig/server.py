"""Token-protected, memory-only latest-frame receiver and browser viewer."""
import argparse
import hmac
import os
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_FRAME = 2 * 1024 * 1024


class Frames:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {}

    def put(self, camera, jpeg):
        with self.lock:
            self.data[camera] = (time.monotonic(), jpeg)

    def get(self, camera):
        with self.lock:
            frame = self.data.get(camera)
        return frame[1] if frame and time.monotonic() - frame[0] < 5 else None


PAGE = Path(__file__).with_name('hud.html').read_bytes()


def make_server(host, port, token):
    frames = Frames()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, body=b'', kind='text/plain'):
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            return hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token)

        def do_GET(self):
            if self.path == '/':
                return self.reply(200, PAGE, 'text/html; charset=utf-8')
            if not self.authorized():
                return self.reply(401)
            if self.path not in ('/frame/scene', '/frame/reading'):
                return self.reply(404)
            jpeg = frames.get(self.path.rsplit('/', 1)[1])
            self.reply(200 if jpeg else 404, jpeg or b'', 'image/jpeg')

        def do_POST(self):
            if not self.authorized():
                return self.reply(401)
            if self.path not in ('/frame/scene', '/frame/reading'):
                return self.reply(404)
            try:
                size = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                return self.reply(400)
            if not 4 <= size <= MAX_FRAME:
                return self.reply(413)
            self.connection.settimeout(5)
            jpeg = self.rfile.read(size)
            if len(jpeg) != size or not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'):
                return self.reply(400)
            frames.put(self.path.rsplit('/', 1)[1], jpeg)
            self.reply(204)

        def log_message(self, *_):
            pass

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    token = os.environ.get('GIG_TOKEN', '')
    if len(token) < 24:
        parser.error('Set GIG_TOKEN to a random token of at least 24 characters')
    server = make_server(args.host, args.port, token)
    print(f'GIG viewer: http://{args.host}:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
