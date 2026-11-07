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
