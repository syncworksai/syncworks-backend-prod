# Sync Assist worker and WhatsApp pilot activation (operator checklist)

These features are private to the authenticated `jacoblord7@outlook.com` pilot.
Neither a webhook nor a UI status proves a live WhatsApp sender. The current
communications hub receives **verified inbound messages only**, with **no sends**.

## Background discovery cron

The scanner is already available as an installed Django command:

```sh
python manage.py sync_assist_discover --dry-run
SYNC_ASSIST_SCHEDULED_SCAN_ENABLED=true python manage.py sync_assist_discover --scheduled
```

Recommended Render cron settings, **after explicit budget approval and DB validation**:

- Repository: `syncworksai/syncworks-backend-prod`, branch: `main`
- Start command: `python manage.py sync_assist_discover --scheduled`
- Schedule: `*/30 * * * *` (UTC; twice hourly)
- Plan: smallest memory tier that runs Django safely; monitor actual costs
- Environment: same applicable `DJANGO_SETTINGS_MODULE`, Django secret and the
  **verified private** production DB connection as the intended API; do not copy
  unrelated production secrets into the job
- Feature flag on cron job **only**: `SYNC_ASSIST_SCHEDULED_SCAN_ENABLED=true`
- No outgoing customer messages, calls, payments, or ticket updates
- Confirm successful Run history, scan audit events with
  `run_source=scheduled`, and two consecutive independent runs. Confirm the
  private Control Center shows `observed_recently`.
- On an error, disable the cron feature flag and inspect logs. Do not create
  multiple independent crons against the same production pilot DB.

Render bills cron jobs, including a minimum monthly charge. Do not provision
without the account owner's budget consent.

## WhatsApp pilot: Twilio + Meta

1. Verify the Meta Business portfolio and WhatsApp Business Account under the
   account owner's control; check whether the existing number is on the
   WhatsApp personal/business app and whether coexistence is supported.
2. Complete WhatsApp sender registration with Twilio and verify sender state.
3. On the Render API receiving the webhook, set (server side only):
   - `TWILIO_AUTH_TOKEN`: the matching Twilio account/subaccount signing secret.
   - `SYNC_ASSIST_PILOT_WHATSAPP_TO`: exact `whatsapp:+E164` sender.
4. Set the sender's incoming-message webhook to:
   `https://syncworks-api.onrender.com/api/v1/sync-ai/assist/pilot/whatsapp/inbound/`
   after verifying this hostname is the active API and the Django proxy HTTPS
   configuration reconstructs the public URL correctly for signature checks.
5. Send an authorized test message and check the private Communications inbox.
   Check that retries do not produce duplicate message entries.
6. Never paste credentials into ChatGPT or the browser. No outbound messaging
   is implemented in this phase. Add opt-in, templates, approved permissions,
   per-business isolation, key rotation and message-retention policies before
   selling this to other businesses.

## Future multi-tenant Embedded Signup

The current pilot is single-sender by environment variables and must NOT be
advertised as self-service onboarding. For SaaS onboarding, SyncWorks needs
Meta Tech Provider authorization, Facebook Login for Business Embedded Signup,
verified WABA/phone assets per business, separate provider subaccounts/credentials,
signed webhook routing by destination, an explicit opt-in/consent model,
template management, rate limits and usage billing.
