"""Build Google Maps handoffs and optionally query a Routes API estimate."""
import http.client
import json
import os
import re
from urllib.parse import urlencode

MAPS_URL = 'https://www.google.com/maps/dir/?'
ROUTES_HOST = 'routes.googleapis.com'
ROUTES_PATH = '/directions/v2:computeRoutes'
TRAVEL_MODES = {
    'driving': 'DRIVE',
    'walking': 'WALK',
    'bicycling': 'BICYCLE',
    'transit': 'TRANSIT',
}


class MapsUnavailable(RuntimeError):
    """Google Routes could not supply an estimate."""


def _place(value, label):
    if not isinstance(value, str):
        raise ValueError(f'Enter a {label}.')
    value = value.strip()
    if not 1 <= len(value) <= 250 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f'Enter a {label} using 1–250 characters on one line.')
    return value


def _route(origin, destination, mode, key):
    payload = {
        'origin': {'address': origin},
        'destination': {'address': destination},
        'travelMode': TRAVEL_MODES[mode],
    }
    headers = {
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': key,
        'X-Goog-FieldMask': 'routes.distanceMeters,routes.duration',
    }
    connection = http.client.HTTPSConnection(ROUTES_HOST, timeout=12)
    try:
        connection.request('POST', ROUTES_PATH, body=json.dumps(payload).encode(), headers=headers)
        with connection.getresponse() as response:
            if response.status in (401, 403):
                raise MapsUnavailable('Google Routes rejected the key. Check API access and billing.')
            if response.status == 429:
                raise MapsUnavailable('Google Routes reached its quota. Try again later.')
            if response.status != 200:
                raise MapsUnavailable('Google Routes could not calculate an estimate for these locations.')
            result = json.loads(response.read(128 * 1024))
        routes = result.get('routes', [])
        if routes == []:
            return None
        route = routes[0]
        meters = route.get('distanceMeters', 0)
        duration = route.get('duration')
        if (type(meters) is not int or meters < 0 or not isinstance(duration, str)
                or not re.fullmatch(r'[0-9]{1,12}(?:\.[0-9]{1,9})?s', duration)):
            raise ValueError('Invalid route estimate')
        return meters, float(duration[:-1])
    except (OSError, http.client.HTTPException, ValueError, KeyError, TypeError, IndexError,
            AttributeError) as error:
        raise MapsUnavailable('Could not read an estimate from Google Routes.') from error
    finally:
        connection.close()


def directions(origin, destination, mode='driving', *, estimate=False):
    """Build a handoff locally and request a distance/time only when selected."""
    origin = _place(origin, 'starting point')
    destination = _place(destination, 'destination')
    if not isinstance(mode, str) or mode not in TRAVEL_MODES:
        raise ValueError('Choose driving, walking, bicycling, or transit.')
    if type(estimate) is not bool:
        raise ValueError('Choose whether to request a route estimate.')
    url = MAPS_URL + urlencode({'api': '1', 'origin': origin, 'destination': destination,
                               'travelmode': mode})
    if len(url) > 2048:
        raise ValueError('The Maps link is too long. Shorten the starting point or destination.')
    result = {'url': url, 'distance_meters': None, 'duration_seconds': None,
              'estimate_status': 'not_requested'}
    if not estimate:
        return result
    key = os.environ.get('GIG_GOOGLE_MAPS_KEY', '').strip()
    if not key:
        result.update(estimate_status='unconfigured', estimate_message='Google Routes is not configured on the Mac.')
        return result
    try:
        route = _route(origin, destination, mode, key)
    except MapsUnavailable as error:
        result.update(estimate_status='unavailable', estimate_message=str(error))
        return result
    if route is None:
        result.update(estimate_status='no_route', estimate_message='Google Routes found no matching route.')
    else:
        result.update(distance_meters=route[0], duration_seconds=route[1], estimate_status='available')
    return result
