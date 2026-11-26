"""One sender process per camera. Ctrl+C releases the camera."""
import argparse
import os
import time
import urllib.request


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
    import cv2
    camera = None
    try:
        if args.source == 'usb':
            camera = cv2.VideoCapture(args.device, cv2.CAP_V4L2)
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            camera.set(cv2.CAP_PROP_FPS, 15)
            if not camera.isOpened():
                raise RuntimeError('USB camera could not be opened')
        else:
            from picamera2 import Picamera2
            camera = Picamera2()
            camera.configure(camera.create_video_configuration(main={'size': (640, 480), 'format': 'RGB888'}, controls={'FrameRate': 15}))
            camera.start()
        print('Capture active. Ctrl+C stops capture. No frames saved to disk.', flush=True)
        while True:
            start = time.monotonic()
            if args.source == 'usb':
                ok, frame = camera.read()
                if not ok:
                    raise RuntimeError('USB camera stopped delivering frames')
            else:
                frame = camera.capture_array()
            ok, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if not ok:
                raise RuntimeError('JPEG encoding failed')
            request = urllib.request.Request(args.server.rstrip('/') + '/frame/' + args.name,
                data=jpeg.tobytes(), headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'image/jpeg'}, method='POST')
            try:
                with urllib.request.urlopen(request, timeout=3) as response:
                    response.read()
            except OSError as error:
                print(f'Receiver unavailable: {error}', flush=True)
                time.sleep(1)
            time.sleep(max(0, 1 / args.fps - (time.monotonic() - start)))
    except KeyboardInterrupt:
        pass
    finally:
        if camera is not None:
            if args.source == 'usb':
                camera.release()
            else:
                camera.stop()
                camera.close()


if __name__ == '__main__':
    main()
