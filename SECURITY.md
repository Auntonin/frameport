# Security and privacy

Keep this repository private. Do not publish source, releases or issue attachments containing target-specific configurations without a new review.

## Separation

Only generic client code and synthetic API fixtures belong here. Real integration profiles belong in `.private/` or outside the checkout. Do not add server source, database schemas, migrations, infrastructure definitions, production endpoints, API keys, passwords, cookies, exported datasets or browser storage. Never force-add ignored files.

The root Git allowlist and repository audit are safeguards against mistakes, not guarantees that every possible secret is detected. Review the complete staged diff before every push. The audit scans staged bytes, not just filenames. Its diagnostics never print matched secret values.

## Runtime boundaries

- Requests to external services require HTTPS and normal certificate verification.
- HTTP API requests do not follow redirects with an authenticated session.
- Browser handoff reads cookies scoped to the selected service paths and checks its ADMIN session.
- Sessions cannot be reused across target websites or different API profiles.
- Passwords and cookie headers are not saved in preferences. Dedicated browser storage may retain login state locally and is sensitive.
- Prepared image content is verified before upload. Uncertain server responses block blind retries.
- Files, history, location coordinates and logs in the user data directory remain private local data.

Knowing a client's request format is not authorization. The receiving service must independently validate identity, permissions and uploaded content. Client code, private visibility and obfuscation cannot certify a separate service as free of vulnerabilities.

## Reporting

Report suspected problems privately to the repository owner. Use synthetic evidence; do not attach real tokens, browser profiles, personal photos or production exports.
