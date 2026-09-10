"""Read available model IDs without saving a connection or sending laboratory data."""
import json
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import Field, SecretStr, field_validator

from . import ai_assistant as ai


MAX_MODELS = 1_000
MAX_MODEL_ID_CHARS = 200
MAX_MODELS_RESPONSE_BYTES = 512_000


class ModelsInput(ai.StrictInput):
    profile: Literal['cloud', 'local']
    endpoint: str = Field(min_length=1, max_length=2_000)
    api_key: SecretStr | None = None

    @field_validator('endpoint')
    @classmethod
    def clean_endpoint(cls, value):
        return ai.ProfileInput.clean_text(value)

    @field_validator('api_key')
    @classmethod
    def bounded_key(cls, value):
        return ai.ProfileInput.bounded_key(value)


def request_connection(services, model):
    endpoint = ai.validate_endpoint(model.endpoint, model.profile)
    if not endpoint:
        raise HTTPException(422, 'ai_endpoint_invalid')
    if 'api_key' in model.model_fields_set:
        # Draft credentials are used only for this request, including explicit removal.
        key = model.api_key.get_secret_value().strip() if model.api_key else ''
    else:
        with ai._config_lock:
            saved = ai.load_settings(services)['profiles'][model.profile]
            same_origin = bool(saved['endpoint']) and ai.endpoint_origin(saved['endpoint']) == ai.endpoint_origin(endpoint)
            key = ai.profile_key(model.profile, saved) if same_origin else ''
    return endpoint, key


def fetch_models(endpoint, key):
    headers = {'Accept': 'application/json'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    try:
        with ai.http_client() as client:
            with client.stream('GET', endpoint + '/models', headers=headers) as response:
                if 300 <= response.status_code < 400:
                    raise HTTPException(502, 'ai_redirect_rejected')
                if response.status_code in (401, 403):
                    raise HTTPException(502, 'ai_auth_failed')
                if response.status_code == 402:
                    raise HTTPException(502, 'ai_insufficient_balance')
                if response.status_code == 429:
                    raise HTTPException(502, 'ai_rate_limited')
                if response.status_code in (404, 405, 501):
                    raise HTTPException(502, 'ai_models_unavailable')
                if not 200 <= response.status_code < 300:
                    raise HTTPException(502, 'ai_provider_rejected')
                chunks, length = [], 0
                for chunk in response.iter_bytes(chunk_size=16_384):
                    length += len(chunk)
                    if length > MAX_MODELS_RESPONSE_BYTES:
                        raise HTTPException(502, 'ai_models_response_too_large')
                    chunks.append(chunk)
                raw = json.loads(b''.join(chunks))
    except httpx.TimeoutException:
        raise HTTPException(504, 'ai_timeout') from None
    except httpx.HTTPError as error:
        raise HTTPException(502, ai.classify_transport_error(error)) from None
    except (ValueError, UnicodeError):
        raise HTTPException(502, 'ai_models_invalid_response') from None

    if not isinstance(raw, dict) or not isinstance(raw.get('data'), list):
        raise HTTPException(502, 'ai_models_invalid_response')
    if not raw['data']:
        raise HTTPException(502, 'ai_models_empty')
    model_ids = set()
    for model in raw['data']:
        model_id = model.get('id') if isinstance(model, dict) else None
        if (not isinstance(model_id, str) or not model_id.strip()
                or len(model_id) > MAX_MODEL_ID_CHARS
                or any(ord(character) < 32 or ord(character) == 127 for character in model_id)
                or (key and key in model_id)):
            # Provider metadata and any echoed credential never reach the browser.
            raise HTTPException(502, 'ai_models_invalid_response')
        model_ids.add(model_id.strip())
    return [{'id': name} for name in sorted(model_ids)[:MAX_MODELS]], len(model_ids) > MAX_MODELS


def install_routes(app, services):
    router = APIRouter(prefix='/api/ai', route_class=ai.PrivateValidationRoute)

    @router.post('/models')
    def available_models(model: ModelsInput):
        endpoint, key = request_connection(services, model)
        models, truncated = fetch_models(endpoint, key)
        return {'status': 'reachable', 'profile': model.profile, 'endpoint': endpoint,
                'checked_at': ai.timestamp(), 'models': models, 'truncated': truncated}

    app.include_router(router)
