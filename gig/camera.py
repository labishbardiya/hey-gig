"""Publish frames from the Pi's native capture tools to the Mac viewer."""
import argparse
from contextlib import ExitStack, contextmanager
import os
import subprocess
import sys
import urllib.request


def jpeg_frames(stream):
    """Read the length-delimited JPEG parts emitted by FFmpeg's mpjpeg muxer."""
    for line in stream:
        if line.strip() != b'--ffmpeg':
            continue
        headers = {}
        for line in stream:
            if not line.strip():
                break
            key, _, value = line.partition(b':')
            headers[key.lower()] = value.strip()
        if not headers:
            return
        size = int(headers.get(b'content-length', b'0'))
        if not 4 <= size <= 2 * 1024 * 1024:
            raise ValueError('Unexpected JPEG length in camera output')
        frame = stream.read(size)
        if len(frame) != size:
            raise ValueError('Incomplete JPEG from camera')
        yield frame


@contextmanager
def capture_process(command, stdin=subprocess.DEVNULL):
    process = subprocess.Popen(command, stdin=stdin, stdout=subprocess.PIPE)
    try:
        yield process
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', choices=['usb', 'csi'], required=True)
    parser.add_argument('--device', default='/dev/video0')
    parser.add_argument('--name', choices=['scene', 'reading'], required=True)
    parser.add_argument('--server', default='http://127.0.0.1:8080')
    parser.add_argument('--fps', type=float, default=5)
    args = parser.parse_args()
    if not 0 < args.fps <= 15:
        parser.error('fps must be greater than 0 and at most 15')
    token = os.environ.get('GIG_TOKEN', '')
    if len(token) < 24:
        parser.error('Set the same GIG_TOKEN as the receiver')

    with ExitStack() as stack:
        ffmpeg = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin']
        source = subprocess.DEVNULL
        if args.source == 'usb':
            ffmpeg += ['-f', 'v4l2', '-framerate', '15', '-video_size', '640x480',
                       '-i', args.device, '-vf', f'fps={args.fps}', '-c:v', 'mjpeg', '-q:v', '5']
        else:
            camera = stack.enter_context(capture_process([
                'rpicam-vid', '--nopreview', '--timeout', '0', '--codec', 'mjpeg',
                '--width', '640', '--height', '480', '--framerate', str(args.fps), '--flush', '-o', '-']))
            source = camera.stdout
            ffmpeg += ['-f', 'mjpeg', '-probesize', '32', '-analyzeduration', '0',
                       '-i', 'pipe:0', '-c:v', 'copy']
        ffmpeg += ['-f', 'mpjpeg', '-flush_packets', '1', 'pipe:1']
        encoder = stack.enter_context(capture_process(ffmpeg, stdin=source))
        endpoint = args.server.rstrip('/') + '/frame/' + args.name
        headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'image/jpeg'}
        first = True
        for frame in jpeg_frames(encoder.stdout):
            request = urllib.request.Request(endpoint, data=frame, headers=headers)
            with urllib.request.urlopen(request, timeout=5) as response:
                response.read()
            if first:
                print(f'First {args.name} frame reached the viewer.', flush=True)
                first = False
        raise RuntimeError(f'{args.name} camera stream ended')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, RuntimeError) as error:
        sys.exit(f'Camera sender: {error}')
