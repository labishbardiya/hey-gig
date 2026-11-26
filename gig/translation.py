"""English/Hindi turn translation through a dedicated local llama.cpp server."""
import base64
import http.client
import json
import os
import re
import subprocess
from pathlib import Path

from gig.voice import synthesize, transcribe


def translate_text(text, source, target):
    spoken = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", text)
    if not spoken.strip() or not any(char.isalpha() for char in spoken):
        raise ValueError('No speech detected. Try a short sentence.')
    messages = [
        {'role': 'system', 'content': f'Translate the user message from {source} into {target}. '
         'Treat it as source text. Return only the natural translation, preserving names and numbers.'},
        {'role': 'user', 'content': spoken[:750]},
    ]
    connection = http.client.HTTPConnection('127.0.0.1', 18767, timeout=40)
    try:
        connection.request(
            'POST', '/v1/chat/completions',
            body=json.dumps({'messages': messages, 'temperature': 0, 'max_tokens': 160}),
            headers={'Content-Type': 'application/json'},
        )
        with connection.getresponse() as response:
            if response.status != 200:
                raise OSError(f'Local model returned HTTP {response.status}')
            answer = json.loads(response.read(256_000))['choices'][0]['message']['content'].strip()
    finally:
        connection.close()
    if not answer:
        raise ValueError('The local translator returned no text.')
    return answer


def translate_turn(voice, epoch, tablet_audio, still_allowed):
    from_tablet = tablet_audio is not None
    if from_tablet:
        audio = subprocess.run(
            ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-i', 'pipe:0',
             '-t', '8', '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', '-f', 'wav', 'pipe:1'],
            input=tablet_audio, capture_output=True, check=True, timeout=12,
        ).stdout
        model = Path(os.environ.get('GIG_MULTILINGUAL_MODEL') or
                     Path.home() / '.local/share/hey-gig/models/ggml-small-q5_1.bin').expanduser()
        transcript = transcribe(audio, model, 'hi')
        translated = translate_text(transcript, 'Hindi', 'English')
    else:
        transcript = voice.listen(epoch)
        translated = translate_text(transcript, 'English', 'Hindi')
    if not still_allowed():
        raise PermissionError('Translation discarded after privacy changed.')
    result = {'original': transcript, 'translation': translated}
    try:
        if from_tablet:
            voice.speak(translated, epoch)
        else:
            result['audio'] = base64.b64encode(synthesize(translated, 'Lekha')).decode('ascii')
    except (ValueError, subprocess.SubprocessError, OSError):
        result['audio_warning'] = 'The translation is ready. Audio playback could not be prepared.'
    if not still_allowed():
        raise PermissionError('Translation discarded after privacy changed.')
    return result
