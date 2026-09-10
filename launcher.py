"""Workspace-specific server with port fallback and graceful shutdown."""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / '.runtime'
STATE = RUNTIME / 'server.json'

def health(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=1) as response:
            return json.load(response)
    except (OSError, ValueError):
        return {}

def running():
    try:
        state = json.loads(STATE.read_text())
        value = health(state['port'])
        return state if value.get('app') == 'flykeeper' and value.get('instance') == state['instance'] else None
    except (OSError, ValueError, KeyError):
        return None

def stop():
    state = running()
    if not state:
        print('No managed Flykeeper instance is running for this workspace.')
        return
    req = urllib.request.Request(f"http://127.0.0.1:{state['port']}/api/shutdown", data=json.dumps({'token':state['token']}).encode(), headers={'Content-Type':'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=3) as response:
        json.load(response)
    for _ in range(40):
        if health(state['port']).get('instance') != state['instance']:
            print('Flykeeper stopped. Your records are saved.')
            return
        time.sleep(.25)
    raise SystemExit('Shutdown requested; the server is still finishing active work.')

def bind_port(preferred):
    for port in range(preferred, min(preferred + 21, 65536)):
        sock = socket.socket()
        if os.name == 'nt':
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind(('127.0.0.1', port))
            sock.listen(128)
            return sock, port
        except OSError:
            sock.close()
    raise SystemExit('No available port in the configured range. Edit flykeeper.config.json.')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--background', action='store_true')
    args = parser.parse_args()
    if args.stop:
        return stop()
    if not (ROOT / 'frontend/dist/local/index.html').exists():
        raise SystemExit('Run Setup-Flykeeper.ps1 first.')
    RUNTIME.mkdir(exist_ok=True)
    if args.background:
        stream = open(RUNTIME / 'server.log', 'a', encoding='utf-8', buffering=1)
        sys.stdout = sys.stderr = stream
    lock = open(RUNTIME / 'instance.lock', 'a+b')
    lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        for _ in range(20):
            existing = running()
            if existing:
                if not args.no_browser:
                    webbrowser.open(f"http://127.0.0.1:{existing['port']}")
                print(f"Flykeeper is already running on port {existing['port']}.")
                return
            time.sleep(.25)
        raise SystemExit('Flykeeper is starting or stopping. Try again shortly.')
    config = json.loads((ROOT / 'flykeeper.config.json').read_text(encoding='utf-8-sig'))
    preferred = config.get('port', 48173)
    if type(preferred) is not int or not 1024 <= preferred <= 65535:
        raise SystemExit('Port must be an integer between 1024 and 65535.')
    sock, port = bind_port(preferred)
    from backend.app import app
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port))
    instance, token = secrets.token_hex(16), secrets.token_urlsafe(32)
    app.state.instance = instance
    app.state.shutdown_token = token
    app.state.request_shutdown = lambda: setattr(server, 'should_exit', True)
    STATE.write_text(json.dumps({'port':port, 'instance':instance, 'token':token, 'pid':os.getpid()}), encoding='utf-8')
    url = f'http://127.0.0.1:{port}'
    print(f'Flykeeper: {url}. Use Stop-Flykeeper.cmd or Settings > Shut down Flykeeper to stop.')
    if not args.no_browser:
        def open_ready():
            for _ in range(60):
                if health(port).get('instance') == instance:
                    webbrowser.open(url)
                    return
                time.sleep(.25)
        threading.Thread(target=open_ready, daemon=True).start()
    try:
        server.run(sockets=[sock])
    finally:
        sock.close()
        try:
            if json.loads(STATE.read_text()).get('instance') == instance:
                STATE.unlink()
        except (OSError, ValueError):
            pass
        lock.close()

if __name__ == '__main__':
    main()
