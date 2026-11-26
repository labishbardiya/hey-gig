import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from gig.maps import directions


class MapsTests(unittest.TestCase):
    def test_encoded_link_and_no_call_without_estimate(self):
        with patch('gig.maps.http.client.HTTPSConnection') as connect:
            result = directions(' Bani Park, जयपुर ', 'Albert Hall & Museum', 'walking')
        link = urlsplit(result['url'])
        self.assertEqual((link.scheme, link.netloc, link.path), ('https', 'www.google.com', '/maps/dir/'))
        self.assertEqual(parse_qs(link.query), {'api': ['1'], 'origin': ['Bani Park, जयपुर'],
                                               'destination': ['Albert Hall & Museum'],
                                               'travelmode': ['walking']})
        self.assertEqual(result['estimate_status'], 'not_requested')
        connect.assert_not_called()

    def test_requires_explicit_locations_and_supported_mode(self):
        for origin, destination, mode in [('', 'Museum', 'walking'), ('Station', None, 'driving'),
                                           ('Station', 'Museum', []), ('Station\nMarket', 'Museum', 'driving'),
                                           ('😀' * 250, 'Museum', 'driving')]:
            with self.subTest(origin=repr(origin)[:40], destination=destination, mode=mode):
                with self.assertRaises(ValueError):
                    directions(origin, destination, mode)

    def test_estimate_without_key_preserves_link(self):
        with patch.dict('os.environ', {'GIG_GOOGLE_MAPS_KEY': ''}), \
                patch('gig.maps.http.client.HTTPSConnection') as connect:
            result = directions('Station', 'Museum', estimate=True)
        self.assertEqual(result['estimate_status'], 'unconfigured')
        self.assertIn('destination=Museum', result['url'])
        connect.assert_not_called()

    def test_routes_request_and_units(self):
        with patch.dict('os.environ', {'GIG_GOOGLE_MAPS_KEY': 'fixture'}), \
                patch('gig.maps.http.client.HTTPSConnection') as connect:
            connection = connect.return_value
            response = connection.getresponse.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = b'{"routes":[{"distanceMeters":2400,"duration":"842.5s"}]}'
            result = directions('Station', 'Museum', 'transit', estimate=True)
        self.assertEqual((result['distance_meters'], result['duration_seconds'], result['estimate_status']),
                         (2400, 842.5, 'available'))
        connect.assert_called_once_with('routes.googleapis.com', timeout=12)
        args, kwargs = connection.request.call_args
        self.assertEqual(args, ('POST', '/directions/v2:computeRoutes'))
        self.assertEqual(kwargs['headers']['X-Goog-Api-Key'], 'fixture')
        self.assertEqual(kwargs['headers']['X-Goog-FieldMask'], 'routes.distanceMeters,routes.duration')
        self.assertEqual(json.loads(kwargs['body']), {'origin': {'address': 'Station'},
                                                     'destination': {'address': 'Museum'},
                                                     'travelMode': 'TRANSIT'})
        connection.close.assert_called_once()

    def test_estimate_failures_leave_google_handoff_available(self):
        with patch.dict('os.environ', {'GIG_GOOGLE_MAPS_KEY': 'fixture'}), \
                patch('gig.maps.http.client.HTTPSConnection') as connect:
            response = connect.return_value.getresponse.return_value.__enter__.return_value
            for status, body, expected in [(200, b'{}', 'no_route'), (403, b'', 'unavailable'),
                                           (200, b'{"routes":[{"duration":false}]}', 'unavailable')]:
                with self.subTest(status=status, body=body):
                    response.status, response.read.return_value = status, body
                    result = directions('Station', 'Museum', estimate=True)
                    self.assertEqual(result['estimate_status'], expected)
                    self.assertIn('destination=Museum', result['url'])
                    self.assertIsNone(result['distance_meters'])
