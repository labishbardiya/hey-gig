import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from gig.server import Frames, make_server


class TransportTests(unittest.TestCase):
    def test_stale_frames_are_not_served(self):
        frames = Frames()
        with patch('gig.server.time.monotonic', return_value=10):
            frames.put('scene', b'frame')
        with patch('gig.server.time.monotonic', return_value=16):
            self.assertIsNone(frames.get('scene'))

    def test_auth_upload_and_camera_separation(self):
        token = 'a' * 32
        server = make_server('127.0.0.1', 0, token)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        def request(path, data=None, auth=True):
            headers = {'Authorization': 'Bearer ' + token} if auth else {}
            return urllib.request.urlopen(urllib.request.Request(base + path, data=data, headers=headers))
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:
                request('/frame/scene', auth=False)
            self.assertEqual(error.exception.code, 401)
            error.exception.close()
            with self.assertRaises(urllib.error.HTTPError) as error:
                request('/frame/scene', b'not a jpeg')
            self.assertEqual(error.exception.code, 400)
            error.exception.close()
            jpeg = b'\xff\xd8test\xff\xd9'
            with request('/frame/scene', jpeg) as response:
                self.assertEqual(response.status, 204)
            with request('/frame/scene') as response:
                self.assertEqual(response.read(), jpeg)
            with self.assertRaises(urllib.error.HTTPError) as error:
                request('/frame/reading')
            self.assertEqual(error.exception.code, 404)
            error.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
