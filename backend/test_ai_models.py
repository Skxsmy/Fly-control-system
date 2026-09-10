"""Model discovery through isolated settings and a real loopback HTTP service."""
import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import ai_assistant as ai
from backend import ai_models


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    services = SimpleNamespace(DB_PATH=tmp_path / 'lab.db')
    monkeypatch.delenv('FLYKEEPER_AI_CONFIG', raising=False)
    for name in ai.PROFILE_NAMES:
        monkeypatch.delenv(f'FLYKEEPER_AI_{name.upper()}_API_KEY', raising=False)
        monkeypatch.delenv(f'FLYKEEPER_AI_{name.upper()}_ENDPOINT', raising=False)
    with sqlite3.connect(services.DB_PATH) as db:
        db.execute('CREATE TABLE records(value TEXT)')
        db.execute('INSERT INTO records VALUES(?)', ('Private laboratory record',))
    # Keep credential tests portable without writing any cleartext test key to disk.
    protected = {}

    def protect(secret):
        token = 'test-protected-' + str(len(protected))
        protected[token] = secret
        return token

    monkeypatch.setattr(ai, 'protect_key', protect)
    monkeypatch.setattr(ai, 'unprotect_key', protected.__getitem__)
    application = FastAPI()
    ai.install_routes(application, services)
    ai_models.install_routes(application, services)
    with TestClient(application) as client:
        yield services, client


@pytest.fixture
def provider():
    requests = []
    reply = {'status': 200, 'body': {'data': [{'id': 'z-model'}, {'id': 'a-model'}, {'id': 'z-model'}]}, 'headers': {}}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append({'method': 'GET', 'path': self.path, 'authorization': self.headers.get('Authorization')})
            raw = reply['body']
            payload = raw if isinstance(raw, bytes) else json.dumps(raw).encode()
            self.send_response(reply['status'])
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            for name, value in reply['headers'].items():
                self.send_header(name, value)
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1', requests, reply
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


@pytest.fixture
def mounted_client(workspace, monkeypatch):
    from backend import app as services

    isolated, _ = workspace
    monkeypatch.setattr(services, 'DB_PATH', isolated.DB_PATH.with_name('mounted-lab.db'))
    services.init_db()
    with TestClient(services.app) as client:
        yield services, client


def discover(client, endpoint, /, **changes):
    return client.post('/api/ai/models', json={'profile': 'local', 'endpoint': endpoint, **changes})


def configure(client, endpoint, *, profile='local', **changes):
    result = client.put('/api/ai/settings', json={'active_profile': profile, 'profiles': {
        profile: {'endpoint': endpoint, 'model': '', **changes}}})
    assert result.status_code == 200, result.text
    return result.json()


def test_unsaved_connection_lists_models_before_model_selection_without_writes(workspace, provider):
    services, client = workspace
    endpoint, requests, _ = provider
    before = services.DB_PATH.read_bytes()
    result = discover(client, endpoint + '/', api_key='draft-request-key')
    assert result.status_code == 200
    data = result.json()
    assert data == {'status': 'reachable', 'profile': 'local', 'endpoint': endpoint,
                    'checked_at': data['checked_at'], 'models': [{'id': 'a-model'}, {'id': 'z-model'}], 'truncated': False}
    assert requests == [{'method': 'GET', 'path': '/v1/models', 'authorization': 'Bearer draft-request-key'}]
    assert 'draft-request-key' not in result.text
    assert not ai.config_path(services).exists()
    assert services.DB_PATH.read_bytes() == before


def test_models_route_is_mounted_before_frontend_static_files(mounted_client, provider):
    services, client = mounted_client
    endpoint, requests, _ = provider
    before = services.DB_PATH.read_bytes()
    result = discover(client, endpoint, api_key='request-only-key')
    assert result.status_code == 200
    assert result.json()['models'] == [{'id': 'a-model'}, {'id': 'z-model'}]
    assert requests[0]['path'] == '/v1/models'
    assert services.DB_PATH.read_bytes() == before
    assert not ai.config_path(services).exists()


def test_saved_key_reused_on_same_profile_origin_without_changing_saved_connection(workspace, provider):
    services, client = workspace
    endpoint, requests, _ = provider
    saved = configure(client, endpoint, api_key='saved-secret')
    before = ai.config_path(services).read_bytes(), services.DB_PATH.read_bytes()
    result = discover(client, endpoint.replace('/v1', '/another/v1'))
    assert result.status_code == 200
    assert requests[0]['authorization'] == 'Bearer saved-secret'
    assert requests[0]['path'] == '/another/v1/models'
    assert client.get('/api/ai/settings').json() == saved
    assert saved['profiles']['local']['test_status'] == 'untested'
    assert (ai.config_path(services).read_bytes(), services.DB_PATH.read_bytes()) == before


@pytest.mark.parametrize('change', ['origin', 'profile'])
def test_omitted_key_is_not_forwarded_to_another_origin_or_profile(workspace, provider, change):
    _, client = workspace
    endpoint, requests, _ = provider
    if change == 'origin':
        configure(client, 'http://127.0.0.1:1/v1', api_key='saved-secret')
        result = discover(client, endpoint)
    else:
        configure(client, endpoint, api_key='saved-secret')
        result = discover(client, endpoint, profile='cloud')
    assert result.status_code == 200
    assert requests[0]['authorization'] is None


@pytest.mark.parametrize('key, expected', [(None, None), ('', None), ('draft-key', 'Bearer draft-key')])
def test_explicit_key_override_is_request_only_and_blank_clears_for_request(workspace, provider, key, expected):
    services, client = workspace
    endpoint, requests, _ = provider
    configure(client, endpoint, api_key='saved-secret')
    before = ai.config_path(services).read_bytes()
    assert discover(client, endpoint, api_key=key).status_code == 200
    assert requests[-1]['authorization'] == expected
    assert ai.config_path(services).read_bytes() == before
    assert discover(client, endpoint).status_code == 200
    assert requests[-1]['authorization'] == 'Bearer saved-secret'


def test_environment_key_respects_saved_profile_and_origin(workspace, provider, monkeypatch):
    services, client = workspace
    endpoint, requests, _ = provider
    monkeypatch.setenv('FLYKEEPER_AI_LOCAL_ENDPOINT', endpoint)
    monkeypatch.setenv('FLYKEEPER_AI_LOCAL_API_KEY', 'environment-secret')
    configure(client, endpoint)
    before = ai.config_path(services).read_bytes()
    assert discover(client, endpoint).status_code == 200
    assert requests[-1]['authorization'] == 'Bearer environment-secret'
    assert discover(client, endpoint, api_key=None).status_code == 200
    assert requests[-1]['authorization'] is None
    assert ai.config_path(services).read_bytes() == before


@pytest.mark.parametrize('status, error', [
    (301, 'ai_redirect_rejected'), (307, 'ai_redirect_rejected'),
    (401, 'ai_auth_failed'), (403, 'ai_auth_failed'), (402, 'ai_insufficient_balance'),
    (429, 'ai_rate_limited'),
    (404, 'ai_models_unavailable'), (405, 'ai_models_unavailable'), (501, 'ai_models_unavailable'),
    (400, 'ai_provider_rejected'), (500, 'ai_provider_rejected'),
])
def test_provider_errors_are_safe_and_redirects_are_not_followed(workspace, provider, status, error):
    _, client = workspace
    endpoint, requests, reply = provider
    reply.update(status=status, body={'error': 'provider-private-error key-to-hide'},
                 headers={'Location': endpoint + '/redirect'})
    result = discover(client, endpoint, api_key='key-to-hide')
    assert result.status_code == 502
    assert result.json() == {'detail': error}
    assert len(requests) == 1
    assert 'key-to-hide' not in result.text and 'provider-private-error' not in result.text


@pytest.mark.parametrize('body', [
    b'not-json', b'\xff\xfe', [], None, {}, {'data': None}, {'data': 'model'},
    {'data': ['model']}, {'data': [None]}, {'data': [{'id': 2}]},
    {'data': [{'id': ''}]}, {'data': [{'id': '   '}]}, {'data': [{'id': 'unsafe\nmodel'}]},
    {'data': [{'id': 'unsafe\x7fmodel'}]}, {'data': [{'id': 'x' * 201}]},
    {'data': [{'id': 'good'}, {'missing': 'id'}]}, {'data': [{'id': 'test-key-echo'}]},
])
def test_invalid_payload_never_becomes_a_model_option(workspace, provider, body):
    _, client = workspace
    endpoint, _, reply = provider
    reply['body'] = body
    result = discover(client, endpoint, api_key='test-key')
    assert result.status_code == 502
    assert result.json() == {'detail': 'ai_models_invalid_response'}
    assert 'test-key' not in result.text


def test_empty_model_list_has_actionable_distinct_error(workspace, provider):
    _, client = workspace
    endpoint, _, reply = provider
    reply['body'] = {'data': []}
    result = discover(client, endpoint)
    assert result.status_code == 502 and result.json() == {'detail': 'ai_models_empty'}


def test_oversized_response_is_bounded(workspace, provider):
    _, client = workspace
    endpoint, _, reply = provider
    reply['body'] = {'data': [{'id': 'model', 'provider_metadata': 'x' * ai_models.MAX_MODELS_RESPONSE_BYTES}]}
    result = discover(client, endpoint)
    assert result.status_code == 502 and result.json() == {'detail': 'ai_models_response_too_large'}


def test_model_count_is_bounded_and_reported_as_truncated(workspace, provider):
    _, client = workspace
    endpoint, _, reply = provider
    reply['body'] = {'data': [{'id': f'model-{index:05d}'} for index in range(ai_models.MAX_MODELS + 5)]}
    result = discover(client, endpoint)
    assert result.status_code == 200
    assert len(result.json()['models']) == ai_models.MAX_MODELS
    assert result.json()['truncated'] is True
    assert result.json()['models'][-1] == {'id': f'model-{ai_models.MAX_MODELS - 1:05d}'}


@pytest.mark.parametrize('changes', [
    {'api_key': 'never-echo\nthis-key'}, {'api_key': 'x' * 8_001},
    {'profile': 'bad-profile'}, {'endpoint': []}, {'unexpected': 'never-echo-this-key'},
    {'model': 'unused'},
])
def test_invalid_request_never_echoes_private_input(workspace, changes, monkeypatch):
    _, client = workspace
    monkeypatch.setattr(ai, 'http_client', lambda: pytest.fail('Invalid request must not contact provider'))
    result = discover(client, 'http://127.0.0.1:11434/v1', **changes)
    assert result.status_code == 422 and result.json() == {'detail': 'ai_invalid_request'}
    assert 'never-echo' not in result.text


@pytest.mark.parametrize('endpoint, profile, code', [
    ('https://remote.example/v1', 'local', 'ai_local_endpoint_required'),
    ('http://remote.example/v1', 'cloud', 'ai_https_required'),
    ('https://user:password@example.com/v1', 'cloud', 'ai_endpoint_invalid'),
    ('https://example.com/v1?key=hidden', 'cloud', 'ai_endpoint_invalid'),
    (' ', 'local', 'ai_endpoint_invalid'),
])
def test_invalid_endpoint_never_sends_credentials(workspace, monkeypatch, endpoint, profile, code):
    _, client = workspace
    monkeypatch.setattr(ai, 'http_client', lambda: pytest.fail('Invalid endpoint must not be contacted'))
    result = discover(client, endpoint, profile=profile, api_key='never-echo-this-key')
    assert result.status_code == 422 and result.json() == {'detail': code}


@pytest.mark.parametrize('failure, expected_status, code', [
    (httpx.ConnectError('private transport detail'), 502, 'ai_connection_failed'),
    (httpx.ReadTimeout('private transport detail'), 504, 'ai_timeout'),
])
def test_transport_failures_do_not_expose_details(workspace, monkeypatch, failure, expected_status, code):
    _, client = workspace

    def fail(request):
        raise failure

    monkeypatch.setattr(ai, 'http_client', lambda: httpx.Client(transport=httpx.MockTransport(fail)))
    result = discover(client, 'http://127.0.0.1:11434/v1', api_key='secret-key')
    assert result.status_code == expected_status and result.json() == {'detail': code}
    assert 'private transport detail' not in result.text


def test_wrapped_permission_failure_identifies_network_access_block(workspace, monkeypatch):
    services, client = workspace

    def fail(request):
        try:
            raise PermissionError(13, 'private operating-system details')
        except PermissionError as denied:
            raise httpx.ConnectError('private provider host and key') from denied

    monkeypatch.setattr(ai, 'http_client', lambda: httpx.Client(transport=httpx.MockTransport(fail)))
    result = discover(client, 'http://127.0.0.1:11434/v1', api_key='request-only-key')
    assert result.status_code == 502
    assert result.json() == {'detail': 'ai_network_permission_denied'}
    assert 'private' not in result.text and 'request-only-key' not in result.text
    assert not ai.config_path(services).exists()
