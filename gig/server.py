"""Token-protected, memory-only latest-frame receiver and browser viewer."""
import argparse
import hmac
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_FRAME = 2 * 1024 * 1024


class Frames:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {}

    def put(self, camera, jpeg):
        with self.lock:
            self.data[camera] = (time.monotonic(), jpeg)

    def get(self, camera):
        with self.lock:
            frame = self.data.get(camera)
        return frame[1] if frame and time.monotonic() - frame[0] < 5 else None


PAGE = b'''<!doctype html><meta charset="utf-8"><title>GIG camera console</title>
<h1>GIG camera console</h1><p>Live preview only. Images are not recorded.</p>
<label>Access token <input id="token" type="password"></label>
<button onclick="start()">Connect</button><button onclick="stop()">Stop preview</button>
<p id="status">Disconnected</p><div id="views"></div>
<script>
let active=false, generation=0, urls={};
function stop(){active=false;generation++;document.querySelectorAll('img').forEach(i=>i.removeAttribute('src'));
Object.values(urls).forEach(URL.revokeObjectURL);urls={};statusText('Preview stopped; camera sender may still be running.');}
function statusText(t){document.getElementById('status').textContent=t;}
async function start(){if(active)return;active=true;const session=++generation;
document.getElementById('views').innerHTML=['scene','reading'].map(c=>`<section><h2>${c}</h2><img id="${c}" width="640"><p id="${c}-status"></p></section>`).join('');
while(active && session===generation){await Promise.all(['scene','reading'].map(async c=>{try{
let r=await fetch('/frame/'+c,{headers:{Authorization:'Bearer '+document.getElementById('token').value},cache:'no-store'});
if(!r.ok)throw Error(r.status===404?'No recent frames':r.status===401?'Invalid token':'Request failed');
let blob=await r.blob();if(session!==generation)return;let u=URL.createObjectURL(blob);
document.getElementById(c).src=u;if(urls[c])URL.revokeObjectURL(urls[c]);urls[c]=u;
document.getElementById(c+'-status').textContent='Live';
}catch(e){if(session!==generation)return;document.getElementById(c+'-status').textContent=e.message;document.getElementById(c).removeAttribute('src');}}));
if(session!==generation)return;statusText('Preview open. Check each camera below.');await new Promise(r=>setTimeout(r,200));}}
</script>'''


def make_server(host, port, token):
    frames = Frames()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, body=b'', kind='text/plain'):
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            return hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token)

        def do_GET(self):
            if self.path == '/':
                return self.reply(200, PAGE, 'text/html; charset=utf-8')
            if not self.authorized():
                return self.reply(401)
            if self.path not in ('/frame/scene', '/frame/reading'):
                return self.reply(404)
            jpeg = frames.get(self.path.rsplit('/', 1)[1])
            self.reply(200 if jpeg else 404, jpeg or b'', 'image/jpeg')

        def do_POST(self):
            if not self.authorized():
                return self.reply(401)
            if self.path not in ('/frame/scene', '/frame/reading'):
                return self.reply(404)
            try:
                size = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                return self.reply(400)
            if not 4 <= size <= MAX_FRAME:
                return self.reply(413)
            self.connection.settimeout(5)
            jpeg = self.rfile.read(size)
            if len(jpeg) != size or not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'):
                return self.reply(400)
            frames.put(self.path.rsplit('/', 1)[1], jpeg)
            self.reply(204)

        def log_message(self, *_):
            pass

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    token = os.environ.get('GIG_TOKEN', '')
    if len(token) < 24:
        parser.error('Set GIG_TOKEN to a random token of at least 24 characters')
    server = make_server(args.host, args.port, token)
    print(f'GIG viewer: http://{args.host}:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
