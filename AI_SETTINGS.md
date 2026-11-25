# Changing the AI service

Edit `backend/.env` on your own computer. Keep your real API key there; do not paste it in chat or put it in frontend code. Your existing Gemini configuration continues to work until you change it.

If you are replacing a key for the **same service and model**, replace only the key. To change services, set the provider, key, and model together. A key cannot identify every vendor's endpoint, request format, or supported model.

## Common settings

```dotenv
SCRUTINY_AI_PROVIDER=openai
SCRUTINY_AI_KEY=replace-with-your-own-key
SCRUTINY_AI_MODEL=replace-with-an-available-vision-model-id
SCRUTINY_AI_VISION=true
```

Choose one provider:

| Value | Service | Extra configuration |
| --- | --- | --- |
| `gemini` | Google Gemini API | None |
| `openai` | OpenAI API | None |
| `anthropic` | Anthropic Claude API | None |
| `openai_compatible` | A service implementing Chat Completions | `SCRUTINY_AI_BASE_URL=https://your-service.example/v1` |
| `local` | Ollama on this computer | `SCRUTINY_LOCAL_MODEL` |
| `none` | AI disabled | Deterministic checks only |

Use a model ID listed by the service for your account. Provider compatibility does not guarantee that every model accepts image input or JSON schemas. Scanned papers need image input; set `SCRUTINY_AI_VISION=false` for text-only models. Image requests then stop before sending anything.

OpenAI-compatible services vary. Set `SCRUTINY_AI_JSON_MODE=json` for JSON object mode, `schema` for JSON schema output, or `prompt` if the service supports neither. Every mode still requires valid JSON matching the application's schema. Invalid, refused, or truncated responses leave the affected questions unresolved. The app does not silently retry with weaker validation.

This is not universal API support: Azure deployments, AWS Bedrock, and other proprietary authentication/protocols need additional adapters. An arbitrary API key will not work with a different service's protocol.

The shared `SCRUTINY_AI_KEY` and `SCRUTINY_AI_MODEL` take priority over legacy `GEMINI_API_KEY` / `GEMINI_MODEL`, `OPENAI_API_KEY` / `OPENAI_MODEL`, or `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL`. Remove stale shared values when using legacy settings. Never reuse one provider's key for another provider.

## After editing

### Coarena

Use the existing `openai_compatible` option; no new adapter is needed for its documented Chat Completions endpoint. There is currently no provider-editing form in the UI. Settings are edited in `backend/.env`.

The reference configuration is [backend/.env.coarena.example](backend/.env.coarena.example). Merge its fields into your existing `.env`, replacing the key and model placeholders locally. Coarena documents `https://coarena.ai/api/v1` as the base URL. If your account gives a different URL, verify that destination before using it. The model ID must match Coarena's model list exactly; IDs can differ from the original vendor's IDs.

The selected configuration uses `deepseek-v4-1-flash-1017`. Coarena lists that exact ID as accepting images, so `SCRUTINY_AI_VISION=true` is enabled. Its documented eight-image request limit is configured through `SCRUTINY_AI_MAX_IMAGES=8`; oversized requests fail locally before any incomplete scan is sent. This is a configured provider choice, not a default course or example paper.

Start with **Check AI connection**, using `SCRUTINY_AI_JSON_MODE=prompt`. Prompt mode avoids assuming support for the optional JSON response-format parameter; local schema validation still applies. A successful text check does not establish practical scan-reading accuracy. Follow it with a non-confidential scanned sample. Restart after configuration changes. The key was entered locally, and a live synthetic-text connection check succeeded on 14 November 2026 through the running app. The first attempt timed out; a retry returned validated JSON successfully in about 2.6 seconds. No examination papers or syllabus were sent. Practical image extraction and academic accuracy remain unverified.

**Examination-content handling:** Coarena's developer documentation states that all requests and responses are stored regardless of a client's `store` setting, and that requests, replies, reasoning, tool calls, and usage may be used in datasets it licenses. Use non-confidential samples for the initial test. Evaluate that policy before sending real unreleased examination papers. The application's sharing confirmation does not change Coarena's policy. No papers have been sent to Coarena during this setup.

Sources checked 14 November 2026: [Coarena API documentation](https://coarena.ai/developers), [Coarena quick start and model IDs](https://coarena.ai/docs). Compatibility is documented; a live check with your key and selected model is still required.

### Start the app and check

1. Stop and restart the backend, then refresh the app at `http://127.0.0.1:8010`.
2. Check that the displayed service, model, and destination match your settings.
3. Click **Check AI connection**. This sends a small synthetic text request, containing no papers or syllabus. It can consume a small amount of API quota. A successful check confirms only the text connection, not image support or academic accuracy.
4. Select the cloud service under **Processing method** and confirm the sharing checkbox for that service. Local processing remains an option. A service/model change invalidates the new scoped confirmation; rotating a key does not.
5. Open your saved scrutiny and run **Review every question**. Reviews are associated with their model configuration; results from a different model are not reused as if produced by the new model. Earlier saved results remain available until you explicitly rerun that revision.

The existing saved `google` processing option remains restricted to Google; it cannot authorize sending documents to another provider. New cloud confirmations are tied to provider, endpoint, model, and capability settings. No automatic fallback sends confidential material to another service after a quota failure.

## Quota and errors

- **429**: the provider's rate/quota limit was reached. Wait for its reset, check the account's limits, or configure another service with available quota.
- **401 / 403**: check the key, account permissions, and model access.
- **404**: check the model ID and API base URL.
- **400 / 422**: check the model's image and JSON-format capabilities.
- **Timeout / invalid output**: the review remains incomplete; retry or use a suitable model.

Google applies Gemini rate limits per project, not per API key. A replacement key in the same project therefore may encounter the same limit. See [Google's rate-limit documentation](https://aistudio.google.com/docs/rate-limits).

The adapters have automated offline protocol and failure tests. A complete live scrutiny must still be checked with the selected service and faculty-reviewed cases before departmental reliance. No AI service guarantees perfect academic judgments.

Protocol references: [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create), [Anthropic Messages](https://platform.claude.com/docs/en/api/messages), [Gemini generation](https://ai.google.dev/api/generate-content).
