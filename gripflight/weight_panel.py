"""Loopback-only live controls. This server does not read the device serial port."""
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .weights import REGIONS


class PanelState:
    def __init__(self, model, record):
        self.model, self.record = model, record
        self.lock = threading.RLock()
        self.paused = self.stop = False
        self.simulated = False
        self.simulate_level = 0.3
        self.telemetry = dict(stage='starting', message='正在连接设备', fresh=False)

    def publish(self, **values):
        with self.lock:
            self.telemetry = values

    def snapshot(self):
        model = self.model.snapshot()
        with self.lock:
            return dict(profile=model, regions=REGIONS, locked=self.model.locked,
                        paused=self.paused, stop=self.stop, telemetry=self.telemetry,
                        simulated=self.simulated, simulate_level=self.simulate_level)

    def control(self, action):
        if action not in ('pause', 'resume', 'stop'):
            raise ValueError('Unknown control')
        with self.lock:
            if self.record('event', dict(name='panel_'+action)) is None:
                raise RuntimeError('控制事件保存失败')
            if action == 'stop':
                self.stop = True
            else:
                self.paused = action == 'pause'


class WeightPanel:
    def __init__(self, state):
        self.state, self.token = state, secrets.token_urlsafe(24)
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(2)
            def log_message(self, *args):
                pass
            def reply(self, value, status=200, html=False):
                data = value if html else json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'application/json; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def allowed(self):
                host = f'127.0.0.1:{owner.server.server_port}'
                if self.headers.get('Host') != host:
                    return False
                token = self.headers.get('X-Grip-Token') or parse_qs(urlparse(self.path).query).get('token', [''])[0]
                return secrets.compare_digest(token, owner.token)
            def do_GET(self):
                if not self.allowed():
                    return self.reply({'error':'Forbidden'}, 403)
                path = urlparse(self.path).path
                if path == '/':
                    return self.reply(Path(__file__).with_name('weight_panel.html').read_bytes(), html=True)
                if path == '/state':
                    return self.reply(owner.state.snapshot())
                return self.reply({'error':'Not found'}, 404)
            def do_POST(self):
                origin = f'http://127.0.0.1:{owner.server.server_port}'
                if not self.allowed() or self.headers.get('Origin') not in (None, origin):
                    return self.reply({'error':'Forbidden'}, 403)
                try:
                    if self.headers.get('Content-Type') != 'application/json':
                        raise ValueError('JSON required')
                    n = int(self.headers.get('Content-Length', '0'))
                    if not 0 < n <= 16384:
                        raise ValueError('Invalid body size')
                    body = json.loads(self.rfile.read(n))
                    if not isinstance(body, dict):
                        raise ValueError('JSON object required')
                    if self.path == '/weights':
                        owner.state.model.update(body, expected_revision=body.get('revision'))
                    elif self.path == '/simulation':
                        level = body['level']
                        if not owner.state.simulated or type(level) not in (float,int) or not 0 <= level <= 1:
                            raise ValueError('Only simulated mode accepts a level in 0..1')
                        owner.state.simulate_level = level
                    elif self.path == '/save':
                        owner.state.model.save_profile()
                    elif self.path == '/control':
                        owner.state.control(body['action'])
                    else:
                        return self.reply({'error':'Not found'}, 404)
                    return self.reply(owner.state.snapshot())
                except Exception as exc:
                    return self.reply({'error':str(exc)}, 400)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = False  # Join in-flight edits before the final session snapshot.
        self.thread = threading.Thread(target=self.server.serve_forever, name='weight-panel', daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/?token={self.token}'

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
