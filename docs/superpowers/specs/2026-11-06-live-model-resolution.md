# Live model resolution

Approved behavior: each CLI skill invocation fetches Copilot's live model catalog.
A family alias selects its latest eligible standard model; an explicit version
selects the same version if present, otherwise the closest eligible version in
that family. Prefer the same major version, then nearest major/minor, with newer
versions breaking ties. Report substitutions on stderr without altering body bytes.
Copilot's catalog is authoritative; do not inspect the Claude environment.

Use an approved, explicit local Copilot executable and the official Python SDK
for metadata only. Never create a session, send a prompt, or upload source text.
Use a fresh client per invocation, bounded discovery and cleanup, and no disk
catalog cache. Refuse authentication/discovery errors and unusable catalogs.
Never guess across families or strip context/date/provider/variant semantics.
Exact special catalog IDs can pass unchanged; fallback applies only to ordinary
numeric versions. Native VS Code passthrough remains unchanged and offline.

Keep existing file/YAML/body safeguards. Provision SDK dependencies through the
existing IT approval process; do not auto-install on managed hosts. Update skill
instructions, READMEs, tests and package artifacts together. Unit tests use
synthetic catalogs; a live metadata check is separate from inference validation.

Alternatives considered: completion scraping is version-dependent; source-Claude
resolution was superseded by the user's explicit Copilot latest/exact/closest rule.
