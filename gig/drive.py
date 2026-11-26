"""Create a PDF in the configured Google Drive using its OAuth access token."""
import json
import os
import re
import stat
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_UPLOAD_PATH = '/upload/drive/v3/files'
_UPLOAD_URL = f'https://www.googleapis.com{_UPLOAD_PATH}?uploadType=resumable&fields=id,webViewLink'


class DriveUploadError(ValueError):
    """A Drive upload could not be completed."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def drive_access_token():
    token = os.environ.get('GIG_GOOGLE_DRIVE_TOKEN', '').strip()
    if not token:
        path = Path.home() / '.local/share/hey-gig/google-drive-token'
        try:
            mode = path.lstat().st_mode
            if not stat.S_ISREG(mode) or mode & 0o077:
                return None
            with path.open() as file:
                token = file.read(4097).strip()
        except (OSError, UnicodeError):
            return None
    if 0 < len(token) <= 4096 and token.isascii() and not any(c.isspace() for c in token):
        return token
    return None


def _view_url(result):
    if not isinstance(result, dict):
        raise DriveUploadError('Drive did not return a file reference. Check Drive before retrying.')
    identifier = result.get('id', '')
    if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', identifier):
        raise DriveUploadError('Drive did not return a file ID. Check Drive before retrying.')
    view = result.get('webViewLink')
    if isinstance(view, str):
        try:
            location = urllib.parse.urlsplit(view)
            if location.scheme == 'https' and location.netloc == 'drive.google.com':
                return view
        except ValueError:
            pass
    return f'https://drive.google.com/file/d/{identifier}/view'


def upload_pdf(pdf: bytes, filename: str) -> str:
    """Upload a PDF and return its Drive view link. Drive permissions follow its defaults."""
    if not isinstance(pdf, bytes) or not pdf.startswith(b'%PDF-'):
        raise DriveUploadError('The selected document is not a PDF.')
    if not isinstance(filename, str) or not filename.lower().endswith('.pdf') or not filename.strip():
        raise DriveUploadError('Enter a PDF filename.')
    token = drive_access_token()
    if not token:
        raise DriveUploadError('Configure a Google Drive OAuth access token on the Mac.')
    opener = urllib.request.build_opener(_NoRedirect())
    auth = {'Authorization': 'Bearer ' + token}
    metadata = json.dumps({'name': filename, 'mimeType': 'application/pdf'}).encode()
    initiate = urllib.request.Request(
        _UPLOAD_URL, data=metadata, headers={
            **auth,
            'Content-Type': 'application/json; charset=UTF-8',
            'X-Upload-Content-Type': 'application/pdf',
            'X-Upload-Content-Length': str(len(pdf)),
        }, method='POST',
    )
    upload_started = False
    try:
        with opener.open(initiate, timeout=15) as response:
            session_url = response.headers.get('Location', '')
        location = urllib.parse.urlsplit(session_url)
        if (location.scheme, location.netloc, location.path) != ('https', 'www.googleapis.com', _UPLOAD_PATH):
            raise DriveUploadError('Drive did not return a valid upload session.')
        request = urllib.request.Request(
            session_url, data=pdf, headers={**auth, 'Content-Type': 'application/pdf'}, method='PUT',
        )
        upload_started = True
        with opener.open(request, timeout=90) as response:
            return _view_url(json.loads(response.read(32_768)))
    except urllib.error.HTTPError as error:
        code = error.code
        error.close()
        if code == 401:
            raise DriveUploadError('Google Drive OAuth access needs to be refreshed.') from None
        if code == 403:
            raise DriveUploadError('Google Drive rejected upload access. Check the account and drive.file scope.') from None
        if upload_started and (code == 308 or code >= 500):
            raise DriveUploadError('Drive did not confirm the upload. Check Drive before retrying.') from None
        raise DriveUploadError(f'Google Drive upload failed (HTTP {code}).') from None
    except (OSError, json.JSONDecodeError, UnicodeError) as error:
        if upload_started:
            raise DriveUploadError('Drive did not confirm the upload. Check Drive before retrying.') from error
        raise DriveUploadError('Could not start a Google Drive upload session.') from error
