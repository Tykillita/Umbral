# Security policy / Política de seguridad

## Reporting a vulnerability / Cómo reportar

Please **do not open a public issue** for security problems. Use GitHub's private advisory form:
<https://github.com/Tykillita/Umbral/security/advisories/new>

Por favor, **no abras un issue público** para problemas de seguridad. Usa el formulario privado de avisos de GitHub (enlace arriba).

Include the affected component (`apps/api`, `apps/web`, `apps/desktop`, `pipeline`), steps to reproduce and the impact you expect. Reports are reviewed on a best-effort basis; this is a volunteer-run project and there is no bounty programme.

## Scope / Alcance

In scope: the public API, the web interface, the Windows app and its updater, the snapshot feed and verification, and the CI/CD workflows.

Out of scope: findings that require a compromised machine or account, volumetric denial of service against free-tier hosting, and the content or availability of third-party news sources.

## Design guarantees worth testing / Garantías de diseño

- **No secrets in the repository.** Only `.env.example` files are versioned; `scripts/check_repo.py` and `scripts/check_public_files.py` run in CI.
- **Stateless public API.** In `public` mode no personal work is persisted on the server; write endpoints used by the local app answer 403. Firestore is used only for the global daily Gemini counter and is closed to browsers by its rules.
- **Source text is data, not instructions.** Prompt-injection attempts inside a news item must not change what the system does.
- **Verified data only.** Snapshots are accepted only after SHA-256, reference and no-fixture checks; on failure the last valid snapshot is kept.
- **Desktop hardening.** The renderer runs with context isolation and sandbox, without Node integration; the local backend listens on loopback behind an ephemeral per-process secret.
- **Free-tier quotas.** Gemini calls are capped globally per UTC day; there is no automatic switch to a paid provider.

## Supported versions / Versiones con soporte

Only the latest commit on `main` and the latest tagged release receive fixes.
