"""Read a public web source and select text excerpts for the companion."""
import ipaddress
import json
import os
import re
import socket
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

MAX_BYTES = 1_000_000
MAX_REDIRECTS = 3
MAX_SOURCE_TEXT = 5000

SCRAPLING_READER = """
import json, sys
from scrapling import Selector
page = Selector(sys.stdin.buffer.read(), huge_tree=False)
region = page.css('main, [role="main"]') or page.css('article') or page.css('#content') or page.css('body')
ignored = ('script', 'style', 'noscript', 'nav', 'header', 'footer')
blocks = [block for node in region for block in node.css('p, h1, h2, h3, li')]
text = '\\n'.join(node.get_all_text(separator=' ', strip=True, ignore_tags=ignored)
                 for node in blocks or region)
print(json.dumps({'title': page.css('title::text').get() or '', 'text': text}))
"""


def _public_ip(address):
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped or ip.sixtofour or ip.teredo:
            return False
        # Well-known NAT64 prefixes can translate to a non-public IPv4 address.
        if ip in ipaddress.ip_network('64:ff9b::/96') or ip in ipaddress.ip_network('64:ff9b:1::/48'):
            return False
    return ip.is_global and not (ip.is_reserved or ip.is_multicast)


def _resolve(url):
    if not isinstance(url, str) or len(url) > 2048 or re.search(r'[\x00-\x20\x7f\\]', url):
        raise ValueError('Enter a public HTTP or HTTPS URL.')
    try:
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username is not None:
            raise ValueError('Enter a public HTTP or HTTPS URL without credentials.')
        port = 443 if parts.scheme == 'https' else 80
        if parts.port not in (None, port):
            raise ValueError('Use the standard HTTP or HTTPS port.')
        # Reject address literals and non-DNS spellings, keeping curl and the
        # validation logic in agreement about the hostname.
        host = parts.hostname.rstrip('.').encode('idna').decode('ascii')
        if not re.fullmatch(r'[a-zA-Z0-9.-]+', host) or '.' not in host:
            raise ValueError('Use a public website hostname.')
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if re.fullmatch(r'[\d.]+', host):
                raise ValueError('Use a public website hostname.') from None
        else:
            raise ValueError('Use a public website hostname.')
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        raise ValueError('Could not resolve the public website.') from exc
    addresses = {entry[4][0] for entry in records}
    if not addresses or not all(_public_ip(address) for address in addresses):
        raise ValueError('This website does not resolve only to public network addresses.')
    address = min(addresses, key=lambda value: (':' in value, value))
    bind = f'[{address}]' if ':' in address else address
    path = quote(parts.path or '/', safe="/%:@!$&'()*+,;=-._~")
    query = quote(parts.query, safe="/?%:@!$&'()*+,;=-._~")
    return urlunsplit((parts.scheme, host, path, query, '')), f'{host}:{port}:{bind}'


def _download(url):
    with tempfile.TemporaryDirectory(prefix='hey-gig-research-') as temporary:
        output = Path(temporary) / 'page.html'
        for _ in range(MAX_REDIRECTS + 1):
            target, resolve = _resolve(url)
            try:
                fetched = subprocess.run(
                    ['curl', '--disable', '--silent', '--show-error', '--noproxy', '*',
                     '--globoff', '--proto', '=http,https', '--resolve', resolve,
                     '--max-time', '7', '--max-filesize', str(MAX_BYTES),
                     '--output', str(output), '--write-out', '%{json}', '--', target],
                    capture_output=True, check=True, timeout=8,
                )
                metadata = json.loads(fetched.stdout)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                raise ValueError('The public page could not be fetched within the download limits.') from exc
            if metadata['response_code'] in (301, 302, 303, 307, 308) and metadata.get('redirect_url'):
                url = metadata['redirect_url']
                continue
            if metadata['response_code'] != 200:
                raise ValueError(f"Website returned HTTP {metadata['response_code']}.")
            mime = (metadata.get('content_type') or '').split(';', 1)[0].strip().lower()
            if mime not in ('text/html', 'application/xhtml+xml'):
                raise ValueError('Choose a public HTML page.')
            if output.stat().st_size > MAX_BYTES:
                raise ValueError('The page exceeds the research download limit.')
            return target, output.read_bytes()
    raise ValueError('The page redirects too many times.')


def _extract(html):
    runtime = Path(os.environ.get('GOD_SCRAPE_RUNTIME',
                                  '~/.local/share/god-scrape/venv')).expanduser()
    try:
        extracted = subprocess.run(
            [str(runtime / 'bin/python'), '-c', SCRAPLING_READER],
            input=html, capture_output=True, check=True, timeout=5,
        )
        result = json.loads(extracted.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise ValueError('Page extraction failed. Check the Mac god-scrape installation.') from exc
    lines = list(dict.fromkeys(' '.join(line.split()) for line in result['text'].splitlines() if line.strip()))
    if not lines:
        raise ValueError('No readable text was found on this page.')
    return result['title'][:200], lines


def _excerpt(lines, question):
    tokens = set(re.findall(r'\b\w{3,}\b', question.casefold())) - {
        'the', 'are', 'what', 'how', 'this', 'and', 'with', 'does', 'can', 'who', 'where',
    }
    if tokens:
        terms = [tokens.intersection(re.findall(r'\w+', line.casefold())) for line in lines]
        weights = {token: 1 / max(1, sum(token in present for present in terms)) for token in tokens}
        matches = [(sum(weights[token] for token in found), index) for index, found in enumerate(terms)
                   if len(lines[index]) >= 24]
        ranked = sorted(matches, key=lambda pair: (-pair[0], pair[1]))
        selected = sorted(index for score, index in ranked[:4] if score)
        if not selected:
            return 'No excerpt matched the question. Review the source text below.'
        lines = [lines[index] for index in selected]
    return '\n'.join(lines[:4])[:1100]


def read_public_source(url, question=''):
    """Return verbatim evidence and its public source URL."""
    if not isinstance(question, str) or len(question) > 400:
        raise ValueError('Keep the research question under 400 characters.')
    resolved_url, html = _download(url)
    title, lines = _extract(html)
    body = '\n'.join(lines)
    return {
        'requested_url': url,
        'retrieved_at': datetime.now(timezone.utc).isoformat(),
        'reader': 'scrapling',
        'answer': _excerpt(lines, question),
        'sources': [{'url': resolved_url, 'title': title, 'text': body[:MAX_SOURCE_TEXT],
                     'truncated': len(body) > MAX_SOURCE_TEXT}],
    }
