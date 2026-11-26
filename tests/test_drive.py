import json
import unittest
from unittest.mock import MagicMock, patch

from gig.drive import DriveUploadError, upload_pdf


class DriveTests(unittest.TestCase):
    def test_upload_uses_metadata_and_pdf_then_returns_web_link(self):
        pdf = b'%PDF-1.7\nfixture'
        location = 'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&upload_id=fixture'
        result_url = 'https://drive.google.com/file/d/fixture/view'
        first = MagicMock()
        first.headers = {'Location': location}
        second = MagicMock()
        second.read.return_value = json.dumps({'id': 'fixture', 'webViewLink': result_url}).encode()

        with patch('gig.drive.drive_access_token', return_value='fixture-token'), \
                patch('gig.drive.urllib.request.build_opener') as build:
            opener = build.return_value
            opener.open.side_effect = [first, second]
            first.__enter__.return_value = first
            second.__enter__.return_value = second
            self.assertEqual(upload_pdf(pdf, 'Scan.pdf'), result_url)

        start, send = [call.args[0] for call in opener.open.call_args_list]
        self.assertEqual(start.get_method(), 'POST')
        self.assertIn('uploadType=resumable', start.full_url)
        self.assertIn('fields=id,webViewLink', start.full_url)
        self.assertEqual(start.get_header('Authorization'), 'Bearer fixture-token')
        self.assertEqual(start.get_header('X-upload-content-length'), str(len(pdf)))
        self.assertEqual(json.loads(start.data), {'name': 'Scan.pdf', 'mimeType': 'application/pdf'})
        self.assertEqual(send.get_method(), 'PUT')
        self.assertEqual(send.full_url, location)
        self.assertEqual(send.data, pdf)

    def test_untrusted_upload_location_cannot_receive_the_pdf(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.headers = {'Location': 'https://www.googleapis.com@other.example/upload/drive/v3/files'}

        with patch('gig.drive.drive_access_token', return_value='fixture-token'), \
                patch('gig.drive.urllib.request.build_opener') as build:
            opener = build.return_value
            opener.open.return_value = response
            with self.assertRaisesRegex(DriveUploadError, 'valid upload session'):
                upload_pdf(b'%PDF-1.7\nfixture', 'Scan.pdf')
            self.assertEqual(opener.open.call_count, 1)

    def test_timeout_after_pdf_submission_is_not_retried(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.headers = {'Location': 'https://www.googleapis.com/upload/drive/v3/files?upload_id=fixture'}

        with patch('gig.drive.drive_access_token', return_value='fixture-token'), \
                patch('gig.drive.urllib.request.build_opener') as build:
            opener = build.return_value
            opener.open.side_effect = [response, TimeoutError()]
            with self.assertRaisesRegex(DriveUploadError, 'Check Drive before retrying'):
                upload_pdf(b'%PDF-1.7\nfixture', 'Scan.pdf')
            self.assertEqual(opener.open.call_count, 2)
