import json
import socket
import subprocess
import unittest
from unittest.mock import patch

from gig.research import _download, _resolve


class ResearchEgressTests(unittest.TestCase):
    def test_public_dns_answer_is_pinned(self):
        answer = (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))
        with patch('gig.research.socket.getaddrinfo', return_value=[answer]):
            self.assertEqual(
                _resolve('https://research.example/a#ignored'),
                ('https://research.example/a', 'research.example:443:93.184.216.34'),
            )

    def test_private_dns_answer_and_credentialed_url_are_rejected(self):
        public = (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))
        private = (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.168.1.10', 443))
        with patch('gig.research.socket.getaddrinfo', return_value=[public, private]):
            with self.assertRaisesRegex(ValueError, 'public network'):
                _resolve('https://research.example/')
        with self.assertRaisesRegex(ValueError, 'without credentials'):
            _resolve('https://user@research.example/')

    def test_redirect_is_validated_before_a_second_request(self):
        public = (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))
        response = {'response_code': 302, 'redirect_url': 'http://127.0.0.1/'}
        with patch('gig.research.socket.getaddrinfo', return_value=[public]), patch(
            'gig.research.subprocess.run',
            return_value=subprocess.CompletedProcess([], 0, json.dumps(response).encode()),
        ) as fetch:
            with self.assertRaisesRegex(ValueError, 'website hostname'):
                _download('https://research.example/')
            self.assertEqual(fetch.call_count, 1)
            self.assertNotIn('--location', fetch.call_args.args[0])
