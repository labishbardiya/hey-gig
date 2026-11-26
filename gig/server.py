"""Token-protected, memory-only latest-frame receiver and browser viewer."""
import argparse
import hmac
import json
import re
import sqlite3
import os
from pathlib import Path
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from gig.calls import Calls
from gig.library import Library
from gig.voice import dispatch
from gig.scan import extract_lines, inspect_page
from gig.ocr import MAX_PAGES, searchable_pdf

MAX_FRAME = 2 * 1024 * 1024


class Frames:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {}
        self.paused = False

    def put(self, camera, jpeg):
        with self.lock:
            if self.paused:
                return False
            self.data[camera] = (time.monotonic(), jpeg)
            return True

    def set_paused(self, paused):
        with self.lock:
            self.paused = paused
            self.data.clear()

    def get(self, camera):
        with self.lock:
            frame = self.data.get(camera)
        return frame[1] if frame and time.monotonic() - frame[0] < 5 else None


PAGE = Path(__file__).with_name('hud.html').read_bytes()


def make_server(host, port, token, library_path=None, voice=None):
    library = Library(library_path) if library_path else None
    calls = Calls(library) if library else None
    frames = Frames()
    ocr_slot = threading.Lock()
    voice_slot = threading.Lock()

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
            if self.path in ('/', '/?companion'):
                return self.reply(200, PAGE, 'text/html; charset=utf-8')
            if not self.authorized():
                return self.reply(401)
            if self.path == '/privacy':
                return self.json_reply({'paused': frames.paused})
            if library and self.path == '/workspace':
                return self.json_reply({**library.snapshot(), 'privacy': frames.paused, 'phone': calls.snapshot()})
            match = re.fullmatch(r'/library/([0-9]{1,18})', self.path)
            if library and match:
                document_id = int(match[1])
                pdf = library.document(document_id)
                if pdf is None:
                    return self.reply(404)
                return self.reply(200, pdf, 'application/pdf', f'hey-gig-{document_id}.pdf')
            if self.path not in ('/frame/scene', '/frame/reading'):
                return self.reply(404)
            if frames.paused:
                return self.reply(423, b'Camera preview paused.')
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
                if library:
                    try:
                        library.add_document(pdf, len(pages))
                    except sqlite3.Error:
                        return self.reply(503, b'Could not save the PDF to the library.')
                return self.reply(200, pdf, 'application/pdf', 'hey-gig-searchable.pdf')
            except TimeoutError:
                return self.reply(408, b'Upload timed out.')
            finally:
                ocr_slot.release()

        def analyze_page(self):
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 4 <= size <= MAX_FRAME:
                    return self.reply(413, b'Invalid page size.')
                self.connection.settimeout(5)
                jpeg = self.rfile.read(size)
                if len(jpeg) != size or not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'):
                    return self.reply(400, b'Invalid JPEG page.')
                if self.path == '/scan/inspect':
                    data = inspect_page(jpeg)
                else:
                    if not ocr_slot.acquire(blocking=False):
                        return self.reply(503, b'Another OCR job is running.')
                    try:
                        data = {'engine': 'tesseract', 'language': 'eng', 'box_space': 'ocr-image-pixels',
                                'lines': extract_lines(jpeg)}
                    finally:
                        ocr_slot.release()
            except ImportError:
                return self.reply(503, b'Automatic capture needs OpenCV on the Mac.')
            except (ValueError, subprocess.SubprocessError, OSError):
                return self.reply(422, b'Page processing failed. Try recapturing the page.')
            return self.reply(200, json.dumps(data).encode(), 'application/json')

        def json_reply(self, data):
            return self.reply(200, json.dumps(data).encode(), 'application/json')

        def update_workspace(self):
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 1 <= length <= 4096:
                    return self.reply(413)
                self.connection.settimeout(5)
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('Expected an action object.')
                if self.path == '/approvals':
                    library.request_share(data.get('document'), data.get('recipient'))
                elif self.path == '/approvals/decision':
                    library.decide(data.get('id'), data.get('decision'))
                elif self.path == '/reminders':
                    library.add_reminder(data.get('title'), data.get('due'))
                elif self.path == '/reminders/cancel':
                    library.cancel_reminder(data.get('id'))
                elif self.path == '/routines':
                    library.add_routine(data.get('name'), data.get('action'))
                elif self.path == '/routines/run':
                    action = library.run_routine(data.get('id'))
                    if action == 'privacy':
                        frames.set_paused(True)
                    return self.json_reply({'action': action})
                elif self.path == '/calls':
                    calls.draft(data)
                elif self.path == '/calls/action':
                    calls.act(data)
                elif self.path == '/assistant/text':
                    command = data.get('command')
                    if not isinstance(command, str) or not 1 <= len(command.strip()) <= 400:
                        raise ValueError('Enter a question or local command.')
                    return self.json_reply(self.assistant_reply(command))
                elif self.path == '/privacy':
                    paused = data.get('paused')
                    if type(paused) is not bool:
                        raise ValueError('Expected a privacy setting.')
                    frames.set_paused(paused)
            except (ValueError, UnicodeError) as exc:
                return self.reply(400, str(exc).encode())
            except TimeoutError:
                return self.reply(408)
            except sqlite3.Error:
                return self.reply(503, b'Library is unavailable. Try again.')
            except (subprocess.SubprocessError, OSError):
                return self.reply(503, b'Local assistant could not read the document.')
            return self.reply(204)

        def assistant_reply(self, command):
            result = dispatch(library, command)
            if result.get('action') == 'privacy':
                frames.set_paused(True)
            return result

        def voice_reply(self):
            if frames.paused:
                return self.reply(423, b'Microphone paused by privacy control.')
            if voice is None:
                return self.reply(503, b'Start the Pi preview with an SSH key to use Galaxy Buds voice.')
            if not voice_slot.acquire(blocking=False):
                return self.reply(409, b'A voice request is already running.')
            try:
                command = voice.listen()
                if frames.paused:
                    return self.reply(423, b'Voice stopped by privacy control.')
                result = self.assistant_reply(command)
                result['transcript'] = command
                if not frames.paused:
                    try:
                        voice.speak(result['answer'])
                    except (ValueError, subprocess.SubprocessError, OSError):
                        result['audio_warning'] = 'The reply is available here. Galaxy Buds playback failed.'
                return self.json_reply(result)
            except (ValueError, EOFError) as error:
                return self.reply(422, str(error).encode())
            except (subprocess.SubprocessError, OSError):
                return self.reply(503, b'Local voice failed. Check Whisper and the Pi connection.')
            finally:
                voice_slot.release()

        def do_POST(self):
            if not self.authorized():
                return self.reply(401)
            if library and self.path == '/assistant/voice':
                return self.voice_reply()
            if library and self.path in (
                '/approvals', '/approvals/decision', '/reminders', '/reminders/cancel',
                '/routines', '/routines/run', '/privacy', '/assistant/text', '/calls', '/calls/action',
            ):
                return self.update_workspace()
            if self.path in ('/scan/inspect', '/scan/extract'):
                return self.analyze_page()
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

    class Server(ThreadingHTTPServer):
        last_reminder_check = 0
        call_worker = None

        def check_calls(self):
            try:
                calls.step()
            except sqlite3.Error:
                pass

        def service_actions(self):
            now = time.monotonic()
            if library and now - self.last_reminder_check >= 2:
                self.last_reminder_check = now
                if self.call_worker is None or not self.call_worker.is_alive():
                    self.call_worker = threading.Thread(target=self.check_calls, daemon=True)
                    self.call_worker.start()
                try:
                    library.deliver_reminders()
                except sqlite3.Error:
                    # Retry at the next interval if the database is busy.
                    pass

    return Server((host, port), Handler)


def library_path():
    return os.environ.get('GIG_LIBRARY') or Path.home() / '.local/share/hey-gig/library.sqlite3'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    token = os.environ.get('GIG_TOKEN', '')
    if len(token) < 24:
        parser.error('Set GIG_TOKEN to a random token of at least 24 characters')
    server = make_server(args.host, args.port, token, library_path())
    print(f'GIG viewer: http://{args.host}:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
