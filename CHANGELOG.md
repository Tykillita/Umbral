# Changelog

All notable changes to Umbral are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Git tags `vX.Y.Z` are created only for milestones declared as releases. The API, the web app, the pipeline, the scoring
rules and the data snapshots are versioned independently (see `/api/v1/health` and each snapshot manifest).

## [Unreleased]

### Added

- Public web mode without accounts: drafts, versions, reviews, impact notes and weights are stored in each browser's IndexedDB, with portable JSON copy/restore and Markdown export.
- Stateless public API under `/api/v1/public` (agenda, topic, queries, drafts, validation), with a global Gemini quota of 20 calls per UTC day (retries included) and a citation-backed template as fallback.
- Daily snapshot feed (`data/current.json` plus the last seven valid snapshots) that the API and the desktop app download only when it changes, verifying SHA-256 and keeping the last valid snapshot on failure.
- Windows desktop app (Electron + NSIS, per-user) bundling the API, the pipeline, PyTorch CPU and the pinned Laya weights; offline reclassification in a separate process.
- Custom, keyboard-accessible controls replacing every native browser control, with a static guard and end-to-end tests.
- `deployCommit` in `GET /api/v1/health` (from `UMBRAL_DEPLOY_COMMIT` or Render's `RENDER_GIT_COMMIT`) so a deployment can be verified before publishing the web app.
- `UMBRAL_CORS_PREVIEW_PROJECT` to allow only the Firebase Hosting preview channels (`<project>--pr-<n>-<hash>`) of one project.
- Publication checks: `scripts/check_public_files.py` (publishable files only, no personal paths, no AI-tool credits, no broken links, commit messages) and `scripts/wait_for_deploy.py`.
- GitHub Actions: per-PR Firebase Hosting previews and a single deployment orchestrator (Render, verification, Hosting, online check); a scheduled daily data workflow, disabled until explicitly enabled.
- First hosted deployment: API on Render Free and web on Firebase Hosting, verified end to end by `scripts/verify_hosted.py`.
- English and Spanish READMEs, a security policy and public architecture, deployment and validation guides.

### Changed

- Render Blueprint pins Python `3.12.14` and `uv==0.12.7`, disables automatic deploys and receives each deployment through a secret hook with the exact commit.
- Sanitised the development reports under `eval/` so they no longer contain machine-specific paths.

### Security

- Private agent instructions, coordination notes, hand-off documents, task boards, prompts and internal logs are excluded from the repository by an explicit Markdown allowlist, enforced in CI even for force-added files.

### Known limits

- The current data snapshot is provisional and classification, claim support and Precision@5 await human review.
- Hosted deployment, the daily workflow and the Windows installer have not been verified end to end on clean machines yet; see `docs/public/VALIDATION.md` for what has actually been run.
