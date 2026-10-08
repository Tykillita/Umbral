<div align="center">

<img src="apps/web/public/brand/icon-256.png" width="80" alt="Umbral owl mark">

# Umbral — From signal to decision

**From signal to decision: a prioritised news agenda with evidence, for human review.**

**English** · [Español](README.es.md)

[![CI](https://github.com/Tykillita/Umbral/actions/workflows/ci.yml/badge.svg?style=flat-square)](https://github.com/Tykillita/Umbral/actions/workflows/ci.yml)
[![Astro](https://img.shields.io/badge/Astro-7-BC52EE?style=flat-square&logo=astro&logoColor=white)](https://astro.build)
[![React](https://img.shields.io/badge/React-19-149ECA?style=flat-square&logo=react&logoColor=white)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org)
[![Node.js](https://img.shields.io/badge/Node.js-24-339933?style=flat-square&logo=nodedotjs&logoColor=white)](https://nodejs.org)
[![Languages](https://img.shields.io/badge/languages-EN%20%7C%20ES-52665A?style=flat-square)](README.es.md)
[![Firebase Hosting](https://img.shields.io/badge/hosting-Firebase%20%2B%20Render-FFCA28?style=flat-square&logo=firebase&logoColor=111)](https://firebase.google.com/products/hosting)
[![MIT](https://img.shields.io/badge/license-MIT-5C83B5?style=flat-square)](LICENSE)

<br>

<img src="apps/web/public/brand/social.png" width="720" alt="Umbral social card: a five-panel prioritised agenda">

<p><a href="#features">Features</a> &bull; <a href="#quick-start">Quick start</a> &bull; <a href="#architecture">Architecture</a> &bull; <a href="#windows-app">Windows app</a> &bull; <a href="#known-limits">Known limits</a> &bull; <a href="SECURITY.md">Security policy</a></p>

<sub>Panama news and official indicators · Spanish interface · Free tiers only</sub>

</div>

Umbral was built for the TVN Media hackathon challenge *“From signal to decision”* (2026-10-07 to 2026-10-09). It answers one question: **which five topics deserve editorial review for Panama's agenda, and why?**

> Everything Umbral produces is a **draft or a signal for review**. Nothing is published automatically, approving a draft is **not** publishing it, and the system never labels news as true or false.

The interface is in Spanish. Code, identifiers and this README are in English; the Spanish README mirrors this one.

## Features

- **Prioritised agenda.** A transparent, versioned score (`scoring-v1`): `P = 30R + 25I + 20U + 15N + 10E` (relevance, impact, urgency, novelty, evidence). Low `[0, 40)`, medium `[40, 70)`, high `[70, 100]`. The *evidence status* (insufficient / partial / sufficient for a draft) is independent of the score, and a syndicated wire story counts as **one** provenance.
- **Evidence cards.** Each topic lists its sources, official indicators (World Bank), contradictions, sponsored-content warnings and why each component scored what it did.
- **Grounded drafts.** Gemini generates a structured draft with citations; if the quota is exhausted or the provider fails, a **citation-backed template** is produced instead. The UI always says whether a draft was *model-generated*, *recovered* or *template-built*.
- **Private by design.** The public web has no accounts. Drafts, versions, reviews, impact notes and weights live in each browser's **IndexedDB**; the API stores no personal work. Export and restore a portable JSON copy, or export Markdown.
- **Local classification.** News are classified with the open [Laya](https://huggingface.co/convaiinnovations/laya) model on CPU, pinned to a fixed revision. The Windows app ships the model and works offline.
- **Daily refresh.** A scheduled workflow builds a verified snapshot (SHA-256 manifest, no fixtures) and publishes it as a feed; the API and the desktop app download it only when it changes and keep the last valid snapshot if anything fails.
- **A hand-made interface.** No native browser controls: selects, checkboxes, number fields, disclosures and tooltips are custom, keyboard-accessible components (a static guard and E2E tests enforce it).

## Architecture

```
Public sources ─► pipeline (Laya, Python 3.12) ─► verified snapshot + SHA-256
                                                      │
                  ┌───────────────────────────────────┤
                  ▼                                   ▼
        Firebase Hosting                       Render (FastAPI)
        static web + data feed                 stateless public API
                  │                            Firestore: daily Gemini quota only
                  ▼
        Browser (Astro + React)  ── IndexedDB: your drafts, reviews and weights

        Windows (Electron) bundles API + pipeline + PyTorch CPU + Laya, SQLite in %LOCALAPPDATA%\Umbral
```

More detail in [docs/public/ARCHITECTURE.md](docs/public/ARCHITECTURE.md). Contracts: [snapshot schema](docs/contracts/snapshot-schema.md), [API](docs/contracts/api-draft.md) and [public API](docs/contracts/api-public.md), plus `apps/api/openapi.json`.

## Repository layout

```
apps/api/      FastAPI service (+ openapi.json)      pipeline/   ingestion, validation, classification, clustering
apps/web/      Astro + React interface               data/       verified snapshots (no raw data)
apps/desktop/  Electron + NSIS installer (Windows)   eval/       development benchmark and metric tools
tests/         integration and end-to-end suites     scripts/    setup, local start, checks, deployment helpers
docs/          public documentation and contracts
```

## Quick start

You need [`uv`](https://docs.astral.sh/uv/) (it fetches Python 3.12 without touching your system Python) and Node 24. The web app declares `node@24` as a dev dependency, so you do not need to change your global Node.

```bash
git clone https://github.com/Tykillita/Umbral.git && cd Umbral
scripts/setup.sh          # Windows: scripts\setup.ps1  (add --laya / -Laya to install the model runtime)
scripts/start-local.sh    # Windows: scripts\start-local.ps1
```

`start-local` builds the web app and serves it, together with the API, at <http://localhost:8000> using the verified snapshot in `data/snapshots/CURRENT`. Add `UMBRAL_OFFLINE=1` (or `--offline` / `-Offline`) to block every external call.

For development run `scripts/dev.sh` (API on :8000, Astro on :4321).

## Configuration

Only `.env.example` files are versioned; never commit real keys (`apps/api/.env.example`, `apps/web/.env.example`). `PUBLIC_*` variables are embedded in the browser bundle and are not secrets.

| Variable | Purpose |
|---|---|
| `UMBRAL_AUTH_MODE` | `public` (hosted web, no accounts) · `local` (single-user desktop/dev) · `dev-header` (tests) |
| `UMBRAL_PERSISTENCE` | `none` (public API) · `sqlite` (desktop/local) · `memory` (tests) |
| `UMBRAL_OFFLINE` | `1` = no external calls |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Gemini free tier, no billing attached; falls back to a template |
| `GEMINI_GLOBAL_CALLS_PER_DAY` | Hard global cap (max 20 per UTC day, retries included) |
| `FIREBASE_PROJECT_ID`, `GOOGLE_APPLICATION_CREDENTIALS` | Server-side only, for the durable quota counter |
| `UMBRAL_CORS_ORIGINS`, `UMBRAL_CORS_PREVIEW_PROJECT` | Allowed web origins and Firebase preview channels |
| `PUBLIC_API_URL`, `PUBLIC_API_MODE`, `PUBLIC_AUTH_MODE` | Web build: API origin, error behaviour and auth mode |

## Tests

```bash
uv run --no-project python scripts/check_repo.py --strict        # secrets and forbidden files
uv run --no-project python scripts/check_public_files.py         # only publishable files, no personal paths
uv run --no-project python scripts/check_no_native_ui.py         # custom-controls-only rule
(cd apps/api && uv run --extra firebase pytest && uv run --extra firebase ruff check . && uv run --extra firebase mypy src \
  && uv run --extra firebase python scripts/export_openapi.py --check)
(cd pipeline && uv run ruff check . && uv run pytest)            # no network, no PyTorch
(cd apps/web && pnpm install --frozen-lockfile && pnpm check && pnpm test && pnpm build)
scripts/test.sh                                                   # everything, incl. integration and Playwright E2E
```

What was run, when, and with what result is recorded in [docs/public/VALIDATION.md](docs/public/VALIDATION.md). A syntactically valid citation does not prove that a claim is supported, and automated tests are not a substitute for human editorial judgement.

## Deployment

Pull requests get a Firebase Hosting preview; merging to `main` deploys the same commit to Render, verifies it and only then publishes Firebase Hosting. Everything runs on free tiers (Firebase Spark, Render Free, Gemini free tier) and stays inside their quotas. See [docs/public/DEPLOYMENT.md](docs/public/DEPLOYMENT.md).

## Windows app

`apps/desktop` builds a per-user NSIS installer for Windows 10/11 x64 that bundles the API, the pipeline, PyTorch CPU and the Laya weights, so it needs no Python, Node or model download on the target machine. The installer is unsigned, so Windows may show a warning. See [apps/desktop](apps/desktop) and [docs/public/DEPLOYMENT.md](docs/public/DEPLOYMENT.md#windows-app).

## Known limits

- Outputs rely on **headlines and metadata**, not full article text.
- The classifier's probabilities are not calibrated. Classification quality, claim support and Precision@5 still need **human review** and are not presented as validated editorial quality.
- The current snapshot is **provisional**: the official frozen news package has not been supplied.
- Independent corroboration is scarce in the collected corpus; sponsored content is flagged and capped.
- Render Free sleeps after 15 minutes of inactivity, so the first request can take up to about a minute; the interface shows a preparation state and a retry button.
- There is no audience, rating or banking-modality data in this MVP.

## Security

See [SECURITY.md](SECURITY.md) to report a vulnerability. Treat the text of any source as data, never as instructions.

## License

[MIT](LICENSE) © Umbral contributors. Third-party components keep their own licenses; the Laya model card and terms are shipped with the desktop installer.
