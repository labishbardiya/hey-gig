"""Telegram PDF delivery and explicit WhatsApp handoffs."""

import http.client
import json
import os
import re
import secrets
import stat
from pathlib import Path
from urllib.parse import quote


class MessagingError(ValueError):
    """A provider failure, with uncertain delivery distinguished from rejection."""

    def __init__(self, message, *, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


def _telegram_token():
    token = os.environ.get('GIG_TELEGRAM_BOT_TOKEN', '').strip()
    if not token:
        path = Path.home() / '.local/share/hey-gig/telegram-bot-token'
        try:
            mode = path.stat().st_mode
            if not stat.S_ISREG(mode) or mode & 0o077:
                return None
            with path.open() as file:
                token = file.read(256).strip()
        except (OSError, UnicodeError):
            return None
    return token if re.fullmatch(r'[0-9]{5,20}:[A-Za-z0-9_-]{20,128}', token) else None


def telegram_configured():
    return _telegram_token() is not None


def validate_chat_id(chat_id):
    if isinstance(chat_id, str):
        chat_id = chat_id.strip()
        if re.fullmatch(r'(?:-?[1-9][0-9]{0,18}|@[A-Za-z][A-Za-z0-9_]{4,31})', chat_id):
            return chat_id
    raise MessagingError('Enter a Telegram numeric chat ID or an @channel username.')


def validate_whatsapp_phone(phone):
    if isinstance(phone, str):
        phone = phone.strip()
        if re.fullmatch(r'\+[1-9][0-9]{7,14}', phone):
            return phone
    raise MessagingError('Enter the WhatsApp number as + followed by the country code and number.')


def whatsapp_url(phone, message):
    """Open a prefilled conversation. The user sends it from WhatsApp."""
    phone = validate_whatsapp_phone(phone)
    if not isinstance(message, str) or not 1 <= len(message.strip()) <= 2000:
        raise MessagingError('Enter between 1 and 2,000 characters for WhatsApp.')
    return f'https://wa.me/{phone[1:]}?text={quote(message.strip(), safe="")}'


def send_telegram(pdf, filename, chat_id):
    """Send one PDF to the approved Telegram destination and return the message ID."""
    chat_id = validate_chat_id(chat_id)
    if not isinstance(pdf, bytes) or not pdf.startswith(b'%PDF-') or len(pdf) > 50_000_000:
        raise MessagingError('Telegram requires a PDF of at most 50 MB.')
    if not isinstance(filename, str) or not 1 <= len(filename) <= 120:
        raise MessagingError('Invalid Telegram PDF filename.')
    filename = re.sub(r'[^A-Za-z0-9_. -]', '_', filename)
    if not filename.lower().endswith('.pdf'):
        filename += '.pdf'
    token = _telegram_token()
    if token is None:
        raise MessagingError('Telegram is unavailable. Configure a bot token on the Mac.')

    boundary = secrets.token_hex(24)
    prefix = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{filename}"\r\n'
        'Content-Type: application/pdf\r\n\r\n'
    ).encode('ascii')
    body = prefix + pdf + f'\r\n--{boundary}--\r\n'.encode('ascii')
    connection = http.client.HTTPSConnection('api.telegram.org', timeout=30)
    try:
        connection.request('POST', f'/bot{token}/sendDocument', body,
                           {'Content-Type': f'multipart/form-data; boundary={boundary}'})
        with connection.getresponse() as response:
            status = response.status
            data = json.loads(response.read(256_000))
    except (OSError, http.client.HTTPException, ValueError) as exc:
        raise MessagingError('Telegram delivery could not be confirmed. Check the chat before retrying.',
                             uncertain=True) from exc
    finally:
        connection.close()

    if not isinstance(data, dict) or status >= 500:
        raise MessagingError('Telegram delivery could not be confirmed. Check the chat before retrying.',
                             uncertain=True)
    if status == 429:
        raise MessagingError('Telegram rate-limited this request. Check the chat before trying again.')
    if status != 200 or data.get('ok') is not True:
        raise MessagingError(f'Telegram rejected the PDF (HTTP {status}). Check the bot token and chat access.')
    result = data.get('result')
    if not isinstance(result, dict) or type(result.get('message_id')) is not int:
        raise MessagingError('Telegram returned no message ID. Check the chat before retrying.',
                             uncertain=True)
    return str(result['message_id'])
