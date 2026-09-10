import socket
import launcher
from backend.test_app import client
from backend import app as module

def test_occupied_port_falls_back_without_closing_original_listener():
    with socket.socket() as other:
        other.bind(('127.0.0.1',0))
        other.listen(1)
        preferred = other.getsockname()[1]
        sock, port = launcher.bind_port(preferred)
        try:
            assert port > preferred
            assert other.getsockname()[1] == preferred
        finally:
            sock.close()

def test_shutdown_requires_current_instance_token(client, monkeypatch):
    called = []
    monkeypatch.setattr(module.app.state, 'shutdown_token', 'qa-secret', raising=False)
    monkeypatch.setattr(module.app.state, 'request_shutdown', lambda:called.append(True), raising=False)
    assert client.post('/api/shutdown',json={'token':'old-token'}).status_code == 403
    assert not called
    assert client.post('/api/shutdown',json={'token':'qa-secret'},headers={'Origin':'https://example.com'}).status_code == 403
    assert not called
    assert client.post('/api/shutdown',json={'token':'qa-secret'}).status_code == 200
    assert called == [True]
