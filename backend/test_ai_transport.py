"""Actionable transport errors without leaking the provider response or key."""
import errno
import socket
import ssl

import httpx
import pytest

from backend import ai_assistant as ai
from backend.test_ai_assistant import client, configure, http_mock


@pytest.mark.parametrize('cause,code', [
    (PermissionError(errno.EACCES, 'private diagnostic'), 'ai_network_permission_denied'),
    (OSError(10013, 'private diagnostic'), 'ai_network_permission_denied'),
    (socket.gaierror(socket.EAI_NONAME, 'private hostname'), 'ai_dns_failed'),
    (ssl.SSLCertVerificationError(1, 'private certificate'), 'ai_tls_failed'),
    (ssl.SSLError(1, 'private handshake'), 'ai_tls_failed'),
    (ConnectionRefusedError('private host'), 'ai_connection_failed'),
])
def test_wrapped_transport_errors_are_actionable_and_redacted(client, monkeypatch, cause, code):
    configure(client)

    def fail(request):
        try:
            raise cause
        except OSError as original:
            raise httpx.ConnectError('private key and host', request=request) from original

    http_mock(monkeypatch, fail)
    response = client.post('/api/ai/test')
    assert response.status_code == 502
    assert response.json() == {'detail': code}
    assert 'private' not in response.text


def test_proxy_error_has_own_code():
    assert ai.classify_transport_error(httpx.ProxyError('secret proxy')) == 'ai_proxy_failed'


def test_exception_chain_with_cycle_is_bounded():
    error = httpx.ConnectError('unavailable')
    error.__cause__ = error
    assert ai.classify_transport_error(error) == 'ai_connection_failed'


def test_balance_error_does_not_report_bad_key(client, monkeypatch):
    configure(client)
    http_mock(monkeypatch, lambda request: httpx.Response(402, text='private provider account'))
    response = client.post('/api/ai/test')
    assert response.status_code == 502
    assert response.json() == {'detail': 'ai_insufficient_balance'}
