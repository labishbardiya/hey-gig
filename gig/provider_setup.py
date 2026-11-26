"""Mac-side credential setup. Values are read from the terminal without echo."""
import argparse
from getpass import getpass
import http.client
import json
import os
from pathlib import Path
import re
import stat
from tempfile import NamedTemporaryFile

DIRECTORY = Path.home() / '.local/share/hey-gig'
FILES = {'drive': 'google-drive-token', 'telegram': 'telegram-bot-token', 'routes': 'google-routes-key'}
TELEGRAM_PATTERN = r'[0-9]{5,20}:[A-Za-z0-9_-]{20,128}'


def read_private_value(filename):
    path = DIRECTORY / filename
    try:
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode) or mode & 0o077:
            return ''
        with path.open() as file:
            value = file.read(4097).strip()
    except (OSError, UnicodeError):
        return ''
    return value if 0 < len(value) <= 4096 and value.isascii() and not any(c.isspace() for c in value) else ''


def save(provider):
    value = getpass(f'Paste {provider} credential, then press Return: ').strip()
    if not value or len(value) > 4096 or not value.isascii() or any(char.isspace() for char in value):
        raise ValueError('Empty or invalid credential.')
    if provider == 'telegram' and not re.fullmatch(TELEGRAM_PATTERN, value):
        raise ValueError('Expected the bot token from BotFather.')
    DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    with NamedTemporaryFile(mode='w', dir=DIRECTORY, delete=False) as file:
        temporary = Path(file.name)
        try:
            file.write(value + '\n')
            file.flush()
            os.replace(temporary, DIRECTORY / FILES[provider])
        finally:
            temporary.unlink(missing_ok=True)
    print(f'Saved {provider} credential in the Mac app directory.')


def telegram_chats():
    from gig.messaging import _telegram_token

    token = _telegram_token()
    if not token:
        raise ValueError('Save the BotFather token first.')
    connection = http.client.HTTPSConnection('api.telegram.org', timeout=10)
    try:
        connection.request('GET', f'/bot{token}/getUpdates?limit=100&timeout=0')
        with connection.getresponse() as response:
            if response.status == 409:
                raise ValueError('This bot has a webhook or another poller. Use a dedicated test bot.')
            if response.status != 200:
                raise ValueError(f'Telegram did not return updates (HTTP {response.status}).')
            result = json.loads(response.read(1_000_000))
    finally:
        connection.close()
    chats = {}
    for update in result.get('result', []):
        for field in ('message', 'channel_post'):
            chat = update.get(field, {}).get('chat', {})
            if 'id' in chat:
                chats[chat['id']] = (chat.get('type', ''), chat.get('title') or chat.get('username') or chat.get('first_name') or '')
    if not chats:
        print('No chat updates yet. Open the bot in Telegram, tap Start, and send a test message.')
    for identifier, (kind, name) in chats.items():
        clean_name = ''.join(char for char in name if char.isprintable())[:100]
        print(f'{identifier}  {kind}  {clean_name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_subparsers(dest='command', required=True)
    action.add_parser('telegram-chats', help='Read chat IDs from recent bot updates')
    action.add_parser('save', help='Save a credential securely').add_argument('provider', choices=FILES)
    args = parser.parse_args()
    try:
        if args.command == 'save':
            save(args.provider)
        else:
            telegram_chats()
    except (OSError, ValueError, http.client.HTTPException) as error:
        # Network errors can contain a credential-bearing URL. Avoid echoing
        # details unless the message is one of our explicitly written errors.
        parser.exit(1, (str(error) if type(error) is ValueError else 'Credential setup request failed.') + '\n')


if __name__ == '__main__':
    main()
