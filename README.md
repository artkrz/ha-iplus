# Plus prepaid balance

Reads active prepaid internet packages and prints JSON with per-subscription totals.
Authentication follows Plus SSO → trusted device or SMS → SAML → iPlus NextAuth
(with the persisted `device_id` cookie) → webapi bearer token. Session cookies,
including trusted-device cookies, are preserved in `session.json`. A denied data
request refreshes the iPlus session once and retries once.

Create `.env` using colon-separated lines (not shell assignments):

```text
user: YOUR_LOGIN
pass: YOUR_PASSWORD
```

Run `uv run python -m plus_balance`. For SMS automation, add
`--code-file /tmp/plus-sms-code` and write the four-digit code to that file when
prompted. `--login-only` establishes the saved session. Keep credentials, saved
sessions, and SMS files private; do not commit them.

Totals use decimal units (1000 MB = 1 GB), exclude unlimited usages, and report
the earliest known expiry of limited data packages. Missing expiry is `null`.
Run offline unit tests with `uv run --offline pytest`.

## Home Assistant

Install through HACS by adding this repository as a custom repository of type
**Integration**, or copy `custom_components/iplus` into your Home Assistant
`config/custom_components/` directory. Restart Home Assistant, then open
**Settings → Devices & services → Add integration → Plus na kartę**.
Enter your Plus username/email and password. If Plus requires SMS verification,
enter the four-digit code in the next screen; the saved login session resumes.
When authentication expires, Home Assistant requests reauthentication and, if
needed, another SMS code. No interactive SMS prompt runs during polling.

Each prepaid number has remaining data, total data (decimal GB), and expiry
sensors. Remaining data includes package details as attributes. Polling defaults
to 60 minutes; integration options allow intervals of at least 15 minutes.
Sessions are stored under `.storage/iplus_<account hash>.json` and removed when
the integration entry is deleted.

For development, run `python scripts/sync_vendor.py` after changing the root
`plus_balance` library; the root tests verify byte-identical vendored sources.
# ha-iplus
