import json
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import MagicMock, patch

from gig.messaging import MessagingError, send_telegram, whatsapp_url


class MessagingTests(unittest.TestCase):
    @patch('gig.messaging._telegram_token', return_value='fixture-token')
    @patch('gig.messaging.http.client.HTTPSConnection')
    def test_send_pdf_uses_exact_approved_chat(self, connect, _token):
        response = MagicMock(status=200)
        response.read.return_value = json.dumps({'ok': True, 'result': {'message_id': 123}}).encode()
        connect.return_value.getresponse.return_value.__enter__.return_value = response
        pdf = b'%PDF-1.5\nfixture'
        self.assertEqual(send_telegram(pdf, 'Scan.pdf', '-1001234'), '123')
        connect.assert_called_once_with('api.telegram.org', timeout=30)
        request, path, body, headers = connect.return_value.request.call_args.args
        self.assertEqual((request, path), ('POST', '/botfixture-token/sendDocument'))
        self.assertIn(b'name="chat_id"\r\n\r\n-1001234\r\n', body)
        self.assertIn(b'filename="Scan.pdf"', body)
        self.assertIn(pdf, body)
        self.assertIn('multipart/form-data; boundary=', headers['Content-Type'])

    @patch('gig.messaging._telegram_token', return_value='fixture-token')
    @patch('gig.messaging.http.client.HTTPSConnection')
    def test_timeout_does_not_retry(self, connect, _token):
        connect.return_value.getresponse.side_effect = TimeoutError()
        with self.assertRaises(MessagingError) as caught:
            send_telegram(b'%PDF-1.5\nfixture', 'Scan.pdf', '@campus_channel')
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(connect.return_value.request.call_count, 1)

    def test_whatsapp_handoff_preserves_unicode_message(self):
        link = urlsplit(whatsapp_url('+919876543210', 'नमस्ते & hello'))
        self.assertEqual((link.scheme, link.netloc, link.path), ('https', 'wa.me', '/919876543210'))
        self.assertEqual(parse_qs(link.query), {'text': ['नमस्ते & hello']})

    def test_invalid_recipient_rejected(self):
        with self.assertRaises(MessagingError):
            whatsapp_url('https://example.com', 'hello')
        with self.assertRaises(MessagingError):
            send_telegram(b'%PDF-1.5\nfixture', 'Scan.pdf', '@campus\r\nheader')
