import json
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request

from gig.preview import REMOTE
from gig.server import make_server


class PreviewTests(unittest.TestCase):
    def test_remote_session_serves_both_names_and_stops_on_disconnect(self):
        # Exercise the same session protocol used over SSH, with a fake sensor
        # that continuously publishes distinguishable frames to the real receiver.
        sender = """
import os, sys, time, urllib.request
base, camera = sys.argv[1:]
frame = bytes.fromhex('ffd8') + camera.encode() + bytes.fromhex('ffd9')
request = urllib.request.Request(base + '/frame/' + camera, data=frame,
    headers={'Authorization': 'Bearer ' + os.environ['GIG_TOKEN']})
while True:
    with urllib.request.urlopen(request, timeout=2) as response:
        response.read()
    time.sleep(0.05)
"""
        token = 'test-session-token-for-loopback'
        server = make_server('127.0.0.1', 0, token)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        names = ['reading', 'scene']
        process = subprocess.Popen([sys.executable, '-c', REMOTE], stdin=subprocess.PIPE, text=True)
        try:
            payload = {'token': token, 'code': sender, 'senders': [[base, name] for name in names]}
            process.stdin.write(json.dumps(payload) + '\n')
            process.stdin.flush()
            for name in names:
                request = urllib.request.Request(base + '/frame/' + name,
                    headers={'Authorization': 'Bearer ' + token})
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    try:
                        with urllib.request.urlopen(request, timeout=1) as response:
                            self.assertEqual(response.read(), b'\xff\xd8' + name.encode() + b'\xff\xd9')
                        break
                    except urllib.error.HTTPError as error:
                        error.close()
                        if error.code != 404:
                            raise
                        time.sleep(0.05)
                else:
                    self.fail(f'No frame for {name}')
        finally:
            process.stdin.close()
            try:
                self.assertEqual(process.wait(timeout=5), 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                server.shutdown()
                server.server_close()
                thread.join()
