"""Token-protected, memory-only latest-frame receiver and browser viewer."""
import argparse
import hmac
import os
from pathlib import Path
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from gig.ocr import MAX_PAGES, searchable_pdf

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
    ocr_slot = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, body=b'', kind='text/plain', attachment=None):
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            if attachment:
                self.send_header('Content-Disposition', f'attachment; filename="{attachment}"')
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

        def export_pdf(self):
            try:
                size = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                return self.reply(400, b'Invalid request length.')
            if not 8 <= size <= MAX_PAGES * (MAX_FRAME + 4):
                return self.reply(413, b'Scan exceeds the export size limit.')
            if not ocr_slot.acquire(blocking=False):
                return self.reply(503, b'Another export is running. Try again shortly.')
            try:
                self.connection.settimeout(10)
                pages = []
                remaining = size
                while remaining >= 4 and len(pages) < MAX_PAGES:
                    header = self.rfile.read(4)
                    length = int.from_bytes(header, 'big')
                    remaining -= 4
                    if len(header) != 4 or not 4 <= length <= min(remaining, MAX_FRAME):
                        return self.reply(400, b'Invalid page length.')
                    jpeg = self.rfile.read(length)
                    if len(jpeg) != length or not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'):
                        return self.reply(400, b'Invalid JPEG page.')
                    pages.append(jpeg)
                    remaining -= length
                if remaining or not pages:
                    return self.reply(400, b'Invalid scan. Export up to 20 pages at a time.')
                try:
                    pdf = searchable_pdf(pages)
                except FileNotFoundError:
                    return self.reply(503, b'Install Tesseract and qpdf on the computer running Hey GIG.')
                except (subprocess.SubprocessError, OSError):
                    return self.reply(422, b'OCR could not finish. Try fewer pages or recapture the document.')
                return self.reply(200, pdf, 'application/pdf', 'hey-gig-searchable.pdf')
            except TimeoutError:
                return self.reply(408, b'Upload timed out.')
            finally:
                ocr_slot.release()

        def do_POST(self):
            if not self.authorized():
                return self.reply(401)
            if self.path == '/scan/pdf':
                return self.export_pdf()
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
