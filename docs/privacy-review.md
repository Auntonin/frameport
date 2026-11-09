# Initial source separation review

Scope: this standalone desktop client and the files selected for its initial private repository. This is not an audit of any receiving website.

Selected from an explicit source allowlist into a new directory, with a new Git history. No server implementation, database schema, infrastructure, migrations, original repository metadata, production integration, real spreadsheet, photos, receipts or browser session is part of the selected source.

Target-specific documentation and live database tests were excluded. Branding, application storage names and test endpoints were replaced. The committed profile is synthetic and serves only the loopback fixtures. The application starts without a target URL and does not discover data in neighbouring folders. A locally retained integration profile is ignored under `.private/` and is never packaged.

Controls: deny-by-default root Git rules; sensitive data patterns; staged-content auditing; private repository visibility; generic-only portable packaging; site-bound sessions; local-only generated fixture tests. Tests cover credential-free preference persistence, target isolation, denied authorization, redirect behavior, resume safety and unchanged WebP bytes.

Limitations: pattern scanning can miss unknown secrets. Private repositories remain accessible to authorized accounts and services. This review does not establish that any external API is vulnerability-free, and no client can guarantee prevention of reverse engineering of another service. Review before inviting collaborators or changing visibility.
