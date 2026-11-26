import tempfile
import unittest
from pathlib import Path

from gig.library import Library
from gig.server import Frames


class PrivacyTests(unittest.TestCase):
    def test_pause_clears_frames_rejects_uploads_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            library = Library(Path(folder) / 'library.sqlite3')
            frames = Frames(library)
            first_session = frames.privacy()['epoch']
            self.assertTrue(frames.put('reading', b'frame'))
            frames.set_paused(True)
            self.assertIsNone(frames.get('reading'))
            self.assertFalse(frames.put('reading', b'frame'))
            restarted = Frames(library)
            self.assertTrue(restarted.privacy()['paused'])
            restarted.set_paused(False)
            self.assertNotEqual(first_session, restarted.privacy()['epoch'])
            self.assertIsNone(restarted.get('reading'))
            self.assertTrue(restarted.put('reading', b'fresh'))
            self.assertEqual(len(library.snapshot()['activity']), 2)
