"""Start a private Mac viewer and run the selected camera senders over SSH."""
import argparse
import json
import re
import secrets
import shlex
import subprocess
import sys
import threading
from pathlib import Path

from gig.server import make_server


# Executed with the Pi's system Python so apt-installed camera libraries are visible.
# Keep stdin open as a session lease. SSH disconnection closes it on the Pi.
REMOTE = """
import json, os, select, subprocess, sys

payload = json.loads(sys.stdin.buffer.readline())
env = dict(os.environ, GIG_TOKEN=payload['token'], PYTHONUNBUFFERED='1')
children = []
try:
    for args in payload['senders']:
        children.append(subprocess.Popen(
            [sys.executable, '-c', payload['code'], *args],
            stdin=subprocess.DEVNULL, env=env))
    while True:
        for child in children:
            if child.poll() is not None:
                raise SystemExit(child.returncode or 1)
        if select.select([sys.stdin], [], [], 0.5)[0] and not os.read(0, 1):
            break
finally:
    for child in children:
        if child.poll() is None:
            child.terminate()
    for child in children:
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pi', help='Pi SSH destination, for example gig@gig-pi.local')
    parser.add_argument('--camera', choices=['usb', 'csi', 'both'], default='usb')
    parser.add_argument('--device', default='/dev/video0', help='USB video capture device on the Pi')
    parser.add_argument('--remote-port', type=int, default=18880)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]*', args.pi):
        parser.error('Supply an SSH hostname or user@hostname')
    if not 1 <= args.remote_port <= 65535:
        parser.error('The remote port must be between 1 and 65535')

    token = secrets.token_urlsafe(32)
    viewer = make_server('127.0.0.1', 0, token)
    worker = threading.Thread(target=viewer.serve_forever, daemon=True)
    worker.start()
    destination = f'http://127.0.0.1:{args.remote_port}'
    senders = []
    if args.camera in ('usb', 'both'):
        senders.append(['--source', 'usb', '--device', args.device, '--name', 'reading', '--server', destination])
    if args.camera in ('csi', 'both'):
        senders.append(['--source', 'csi', '--name', 'scene', '--server', destination])
    code = Path(__file__).with_name('camera.py').read_text()
    packet = json.dumps({'token': token, 'senders': senders, 'code': code}) + '\n'
    forward = f'127.0.0.1:{args.remote_port}:127.0.0.1:{viewer.server_port}'
    command = ['ssh', '-T', '-o', 'ExitOnForwardFailure=yes', '-o', 'ConnectTimeout=8',
               '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2',
               '-R', forward, args.pi, shlex.join(['/usr/bin/python3', '-c', REMOTE])]
    print(f'On this computer open http://127.0.0.1:{viewer.server_port}', flush=True)
    print(f'Paste this session token into the viewer: {token}', flush=True)
    print('Keep this terminal open. Press Ctrl+C here to stop capture.', flush=True)
    try:
        with subprocess.Popen(command, stdin=subprocess.PIPE, text=True) as link:
            try:
                link.stdin.write(packet)
                link.stdin.flush()
                return link.wait()
            except (KeyboardInterrupt, BrokenPipeError):
                return 130 if link.poll() is None else link.returncode
            finally:
                link.stdin.close()
                if link.poll() is None:
                    try:
                        link.wait(timeout=4)
                    except subprocess.TimeoutExpired:
                        link.terminate()
    finally:
        viewer.shutdown()
        viewer.server_close()
        worker.join()


if __name__ == '__main__':
    sys.exit(main())
