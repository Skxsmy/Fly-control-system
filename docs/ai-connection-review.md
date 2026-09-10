# Connection failure and model discovery

Date: 2026-09-10

## Cause and correction

The persistent application had been launched under the coding environment's offline Windows sandbox account. Its outbound socket attempts failed with Windows error 10013 before reaching the provider. The adapter reduced that failure to a generic connection error, hiding the useful cause. The configured URL, key, and model ID were valid.

The running application was restarted under the normal desktop account. Saved credentials were transferred only in process memory through the application's loopback settings endpoint and re-encrypted by that account using DPAPI. No plaintext key file or credential-bearing diagnostic output was produced. The provider's model-list request then returned HTTP 200, and the existing `deepseek-flash` generation test returned HTTP 200. The eight laboratory-table digests remained unchanged.

Development instructions now require the persistent user application to run under the desktop account; sandbox processes remain appropriate for isolated local tests. TLS verification and endpoint-origin credential restrictions were retained.

## Model discovery

`POST /api/ai/models` accepts the current profile and unsaved base URL/key. It calls the provider's authenticated `GET /models` without requiring a model name, saving configuration, or sending laboratory records. Saved credentials are reused only for the same profile and origin. Explicit draft credentials remain request-only. Responses are bounded, deduplicated, and sorted; a capped list reports truncation.

The main AI connection page automatically loads a configured connection's model list. **Fetch models** also works with a blank model and unsaved connection fields. A searchable list fills the editable model ID; unsupported model-list endpoints retain manual entry. Editing URL/key or switching profile cancels pending list requests and invalidates prior results. List access is labeled **API reachable**, distinct from the generation check performed by **Save and test**.

Transport errors now distinguish OS network permission denial, DNS, TLS, proxy, timeout, and general connection failure. HTTP 402 reports insufficient provider balance. Errors do not disclose raw exception text or response bodies.

## Validation

- Entire backend suite: **314 passed, 1 skipped**. The existing skipped case needs Windows permission to create a file symlink.
- New tests include model discovery before choosing a model, real loopback HTTP, main-app route mounting, draft/stored-key isolation, read-only behavior, malformed and oversized responses, missing model-list support, permission errors, and TLS/errno classification.
- Frontend typecheck, targeted lint, and production build passed.
- Isolated browser flow: blank model → fetch unsaved URL → search and select → save and test succeeded. Unsupported listing showed the manual-entry recovery. Editing the URL during a delayed fetch cancelled its result.
- The production endpoint returned `deepseek-flash` and `deepseek-v4-pro` using the user's saved connection. A real generation test passed without sending any laboratory records.

Provider model identifiers are fetched dynamically, not hardcoded. The listing contract follows [DeepSeek's model API](https://api-docs.deepseek.com/api/list-models/) and the [OpenAI model-list API](https://platform.openai.com/docs/api-reference/models/list).
