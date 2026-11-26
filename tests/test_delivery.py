import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from gig.delivery import Deliveries
from gig.library import Library


class DeliveryTests(unittest.TestCase):
    def test_delivery_requires_approval_and_whatsapp_only_creates_handoff(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch('gig.delivery.drive_access_token', return_value='fixture'), \
                patch('gig.delivery.telegram_configured', return_value=True), \
                patch('gig.delivery.send_telegram', return_value='123') as telegram, \
                patch('gig.delivery.upload_pdf', return_value='https://drive.google.com/file/d/test/view') as upload:
            library = Library(Path(folder) / 'db.sqlite3')
            document = library.add_document(b'%PDF-test', 1)
            delivery = Deliveries(library)
            drive = {'document': document, 'channel': 'drive'}
            whats = {'document': document, 'channel': 'whatsapp', 'recipient': '+12025550123'}
            with self.assertRaises(ValueError):
                delivery.draft(whats)
            delivery.draft(drive)
            delivery.step()
            upload.assert_not_called()
            delivery.decide({'id': 1, 'decision': 'approve'})
            with self.assertRaises(ValueError):
                delivery.decide({'id': 1, 'decision': 'approve'})
            with ThreadPoolExecutor(2) as workers:
                list(workers.map(lambda _: delivery.step(), range(2)))
            upload.assert_called_once_with(b'%PDF-test', 'hey-gig-1.pdf')
            delivery.draft(whats)
            delivery.decide({'id': 2, 'decision': 'approve'})
            delivery.step()
            handoff = delivery.snapshot()[0]
            self.assertEqual(handoff['state'], 'handoff')
            self.assertTrue(handoff['result'].startswith('https://wa.me/12025550123?'))
            telegram.assert_not_called()
            draft = {'document': document, 'channel': 'telegram', 'recipient': '-10012345'}
            delivery.draft(draft)
            delivery.decide({'id': 3, 'decision': 'deny'})
            delivery.step()
            telegram.assert_not_called()
            delivery.draft(draft)
            delivery.decide({'id': 4, 'decision': 'approve'})
            delivery.step()
            telegram.assert_called_once_with(b'%PDF-test', 'hey-gig-1.pdf', '-10012345')
