"""Local voice capture on the Pi and transcription and synthesis on the Mac."""
import io
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
import wave
from datetime import datetime, timedelta
from pathlib import Path

REMOTE_AUDIO = """
import json, os, subprocess, sys, tempfile, time, urllib.request
mode, endpoint, epoch = sys.argv[1:]
token = sys.stdin.buffer.readline().decode().strip()
request = urllib.request.Request(endpoint, headers={'Authorization': 'Bearer ' + token})
def allowed():
    with urllib.request.urlopen(request, timeout=1) as response:
        state = json.load(response)
        return not state['paused'] and state['epoch'] == epoch
def find_buds():
    wanted = 'Audio/Source' if mode == 'record' else 'Audio/Sink'
    nodes = json.loads(subprocess.check_output(['pw-dump'], timeout=4))
    for node in nodes:
        props = node.get('info', {}).get('props', {})
        name = props.get('node.name', '')
        if props.get('media.class') == wanted and name.startswith(('bluez_input.', 'bluez_output.')):
            if 'A8:BA:69:F4:68:21' in name or 'A8_BA_69_F4_68_21' in name:
                return str(node['id'])
    return None

target = None
for attempt in range(8):
    if not allowed():
        sys.exit('Voice is paused by privacy control.')
    target = find_buds()
    if target:
        break
    time.sleep(.25)
if target is None:
    sys.exit('Galaxy Buds audio node unavailable. Connect the Buds and enable the headset profile.')
with tempfile.TemporaryDirectory() as directory:
    path = os.path.join(directory, 'clip.wav')
    if mode == 'play':
        with open(path, 'wb') as file:
            file.write(sys.stdin.buffer.read(8_000_001))
    if not allowed():
        sys.exit('Voice is paused by privacy control.')
    command = ['pw-record', '--target', target, '--rate', '16000', '--format', 's16', '--channels', '1', path] if mode == 'record' else ['pw-play', '--target', target, path]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL)
    deadline = time.monotonic() + (5 if mode == 'record' else 25)
    try:
        while process.poll() is None and time.monotonic() < deadline:
            if not allowed():
                sys.exit('Voice stopped by privacy control.')
            time.sleep(.15)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    if mode == 'record':
        if not allowed() or os.stat(path).st_size < 3200:
            sys.exit('Recording did not complete.')
        with open(path, 'rb') as file:
            sys.stdout.buffer.write(file.read())
    elif process.returncode:
        sys.exit('Galaxy Buds playback did not complete.')
"""


class PiVoice:
    def __init__(self, destination, identity, port, token):
        self.command = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=4',
                        '-o', 'StrictHostKeyChecking=yes']
        if identity:
            self.command += ['-i', identity, '-o', 'IdentitiesOnly=yes']
        self.command.append(destination)
        self.endpoint = f'http://127.0.0.1:{port}/privacy'
        self.token = token
        self.model = Path(os.environ.get('GIG_WHISPER_MODEL') or
                          Path.home() / '.local/share/hey-gig/models/ggml-base.en.bin').expanduser()

    def remote(self, mode, epoch, audio=b''):
        result = subprocess.run(
            self.command + [shlex.join(['/usr/bin/python3', '-c', REMOTE_AUDIO, mode, self.endpoint, epoch])],
            input=self.token.encode() + b'\n' + audio, capture_output=True, timeout=38,
        )
        if result.returncode:
            reason = result.stderr.decode(errors='replace').strip().splitlines()
            raise ValueError(reason[-1] if reason else 'Pi audio session failed.')
        return result.stdout

    def listen(self, epoch):
        if not self.model.is_file():
            raise ValueError('The local Whisper model is missing on the Mac.')
        return transcribe(self.remote('record', epoch), self.model, 'en')

    def speak(self, text, epoch):
        self.remote('play', epoch, synthesize(text))


def transcribe(audio, model, language):
    if not model.is_file():
        raise ValueError('The local Whisper model is missing on the Mac.')
    with tempfile.TemporaryDirectory() as directory:
        wav = Path(directory) / 'voice.wav'
        wav.write_bytes(audio)
        with wave.open(io.BytesIO(audio)) as clip:
            if clip.getnframes() < 1000:
                raise ValueError('The microphone returned too little audio.')
        output = wav.with_suffix('.txt')
        subprocess.run(['whisper-cli', '-m', str(model), '-f', str(wav),
                        '-l', language, '-otxt', '-of', str(output.with_suffix(''))],
                       check=True, capture_output=True, timeout=45)
        return output.read_text().strip()


def synthesize(text, voice=None):
    if sys.platform != 'darwin':
        raise ValueError('Spoken replies currently require the Mac backend.')
    with tempfile.TemporaryDirectory() as directory:
        wav = Path(directory) / 'reply.wav'
        command = ['say', '-o', str(wav), '--file-format=WAVE', '--data-format=LEI16@16000']
        if voice:
            command += ['-v', voice]
        subprocess.run([*command, '--', text[:450]], check=True, capture_output=True, timeout=15)
        return wav.read_bytes()


def answer_document(pdf, question):
    result = subprocess.run(['pdftotext', '-', '-'], input=pdf, capture_output=True, check=True, timeout=15)
    pages = result.stdout.decode(errors='replace').split('\f')
    terms = set(re.findall(r'[a-z0-9]+', question.casefold())) - {
        'what', 'does', 'the', 'say', 'about', 'is', 'in', 'my', 'scan', 'latest', 'document', 'tell', 'me',
        'did', 'i', 'just', 'a', 'of', 'on', 'it', 'how', 'do', 'you',
    }
    best = None
    for page, content in enumerate(pages, 1):
        for line in content.splitlines():
            score = len(terms.intersection(re.findall(r'[a-z0-9]+', line.casefold())))
            if line.strip() and (best is None or score > best[0]):
                best = (score, page, line.strip())
    if not best or (terms and best[0] == 0):
        return {'answer': 'I found no matching text in this scan.'}
    return {'answer': f'Page {best[1]}: {best[2]}', 'page': best[1]}


def reminder_request(command, now):
    match = re.fullmatch(r'remind me to (.+?) in (\d+) (minute|hour|day)s?', command, re.I)
    if match:
        amount = int(match[2])
        if not 1 <= amount <= 1000:
            raise ValueError('Choose a reminder interval between 1 and 1000.')
        unit = {'minute': 'minutes', 'hour': 'hours', 'day': 'days'}[match[3].lower()]
        return match[1], now + timedelta(**{unit: amount})
    return command[len('remind me to '):].strip(), None


def dispatch(library, command, *, now=None):
    command = command.strip().rstrip('.?!').strip()
    if not command:
        raise ValueError('No speech detected. Try again.')
    lower = command.casefold()
    call = re.fullmatch(r'(?:draft a call to|call) (.+?) (?:to|and) (.+)', command, re.I)
    if call:
        return {'answer': 'Review the recipient and instructions in Calls, then save the draft.',
                'call_draft': {'recipient': call[1][:200], 'task': call[2][:1500]}}
    if lower.startswith('remind me to '):
        title, due = reminder_request(command, now or datetime.now().astimezone())
        if due is None:
            return {'answer': 'When should I remind you?', 'view': 'reminders', 'reminder': title}
        library.add_reminder(title, due.isoformat())
        return {'answer': f'Reminder set for {title}.', 'view': 'reminders'}
    if lower.startswith('run '):
        name = command[4:].strip().casefold()
        matches = [row for row in library.snapshot()['routines'] if row['name'].casefold() == name]
        if len(matches) != 1:
            return {'answer': 'Say run followed by one unique saved routine name.', 'view': 'routines'}
        action = library.run_routine(matches[0]['id'])
        return {'answer': f'Ran {matches[0]["name"]}.',
                'view': 'scanner' if action == 'scan' else 'routines', 'action': action}
    documents = library.snapshot()['documents']
    if not documents:
        return {'answer': 'Save a searchable scan first, or say remind me to, followed by a task and time.'}
    document = documents[0]['id']
    return {**answer_document(library.document(document), command), 'document': document}
