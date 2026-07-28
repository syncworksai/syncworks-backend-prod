# ElevenLabs Render configuration checklist

This document intentionally contains no secret values.

The production SyncWorks voice service must keep all ElevenLabs credentials on the backend Render service. Never expose the API key through Vite, browser JavaScript, GitHub, or client-visible environment variables.

Before production testing, confirm the environment names consumed by the existing Sync AI voice implementation and ensure the following capabilities are represented:

- ElevenLabs API key
- SYNC voice ID
- ElevenLabs model ID, when configurable
- Mobile-compatible MP3 output format, preferably MPEG audio

Operational checks:

1. The voice status endpoint reports configured/available.
2. The synthesize endpoint requires an authenticated SyncWorks user.
3. The synthesize endpoint returns non-empty audio bytes with `Content-Type: audio/mpeg`.
4. The configured voice ID matches the approved SYNC voice.
5. No key or secret appears in frontend environment variables or responses.
6. Render is redeployed after environment changes.
7. Test the same response on desktop Chrome, mobile Safari, and mobile Chrome.

Do not paste API keys into tickets, pull requests, chat messages, or logs.
