# Changelog

All notable changes to Umbral are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Git tags `vX.Y.Z` are created only for milestones declared as releases. The API, the web app, the pipeline, the scoring
rules and the data snapshots are versioned independently (see `/api/v1/health` and each snapshot manifest).

## [Unreleased]

### Added

- Aviso flotante y preferencia de actualizaciones de escritorio: un interruptor en Configuración permite desactivar la descarga e instalación automáticas; con las automáticas apagadas Umbral solo avisa de la versión disponible y ofrece «Actualizar ahora» para descargarla e instalarla.
- Panel flotante de Configuración desde la tuerca fija, con Preferencias y Conexiones; los avisos globales se compactan a 56 px con texto elíptico accesible y controles táctiles de 44 px.
- Temas «Original» y «TVN Noticias» en Configuración, con preferencia local para toda Umbral; Preferencias y Conexiones ahora forman parte del encabezado de la tarjeta.
- Conectores públicos OAuth de Notion y Slack aislados por identidad anónima Firebase, con credenciales cifradas en Firestore, destino/página elegible, compartir en Slack y avisos de revisión opcionales con deduplicación. Su uso real requiere configurar las aplicaciones OAuth, Firebase y la clave de cifrado en el API.
- Recorridos de demostración por rol y mesa editorial compartida de solo inserción; etiquetado humano ciego con exportación e importación verificable de etiquetas.
- Agrupación semántica multilingüe precalculada, recuperación del asistente BM25/RapidFuzz con expansión de vecinos y fusión RRF, detección explicable de cifras contradictorias ES/EN y consultas al catálogo sísmico USGS.
- Exportación local directa de fichas Markdown a páginas nuevas de Notion y aviso accesible del estado de descarga, junto al asistente de evidencia.
- Centro de advertencias accesible junto al asistente; los `Notice` de tono `warn` y `amber` activos se agrupan ahí y muestran su contador.
- La búsqueda automática de noticias complementa TVN con consultas RSS de Bing News y conserva enlaces directos al editor original; los fallos de GDELT quedan registrados y pueden tolerarse si las fuentes restantes cumplen cobertura y aportan titulares nuevos.
- Comandos `news-candidate` y `promote-news` para preparar, verificar y promover una ingesta clasificada con Laya solo después de cumplir cobertura, titulares nuevos e integridad exacta.
- La app de escritorio busca y clasifica noticias automáticamente cada 24 horas mientras está abierta y conectada; solo activa snapshots que superan las verificaciones.
- El empaquetado de escritorio prepara Laya calibrada y su snapshot de 991 titulares juntos; el runtime rechaza paquetes cuyo modelo, perfil y manifest no coinciden exactamente.
- El productor web valida el ID exacto, el perfil Laya calibrado, cobertura mínima y titulares nuevos antes de publicar; conserva en el snapshot los fallos de fuentes opcionales como advertencias.
- La Agenda filtra oportunidades «TVN aún no lo cubre» con dos o más procedencias independientes y ningún artículo TVN del snapshot actual; el criterio funciona en API directa, API pública y mock.
- Borradores ajusta preguntas a la categoría y las brechas de evidencia, separa `GUION` de `NOTAS DE PRODUCCIÓN` y genera variantes derivadas para X, Instagram y TikTok.
- El asistente valida tipo de evidencia y periodos contra el corte del snapshot, limita correcciones difusas a errores de tipeo, rechaza inyecciones/perfilamiento y atribuye consultas de culpabilidad; Jurado conserva sus sugerencias y suma cuatro demos.

### Fixed

- En la web, el desplazamiento queda confinado al contenido en todos los tamaños; en móvil, las acciones del encabezado permanecen en una fila y la navegación inferior conserva todo el ancho.
- Tipos de filtros públicos y respuestas OAuth de Notion y Slack, para que la API pase la comprobación estática de mypy sin cambiar sus valores por defecto ni el manejo de respuestas incompletas.

### Changed

- La cabecera de la app mantiene «Asistente» accesible al desplazarse, también en anchos de escritorio y móvil.
- Ampliar el asistente abre una vista de conversación a pantalla completa, oculta e inhabilita la página de fondo y permite volver al panel flotante sin perder el contexto.
- El botón flotante de Configuración se oculta mientras el asistente ocupa la pantalla en móvil y reaparece al cerrar o minimizar el chat.
- En pantallas anchas, marca, navegación y acciones comparten una fila en el ancho disponible; el escritorio reserva espacio para los controles de ventana.
- La navegación no parte los rótulos en dos líneas; en anchos de escritorio intermedios, las vistas secundarias se agrupan en «Más» para mantener libre la fila principal.
- Los avisos aparecen en la esquina inferior derecha y, con el asistente minimizado, se ubican encima de su botón flotante.
- El aviso de Mesa sin sincronización se integra al centro de advertencias en web y se oculta en Desktop, donde la copia local es el comportamiento esperado.
- Umbral Desktop conserva sus borradores y conexiones personales locales mientras permite usar Notion y Slack por OAuth público; el puente Electron limita las solicitudes a rutas de conectores y mantiene la identidad Firebase anónima fuera del almacenamiento OAuth local.
- Borradores and the evidence assistant now let users start ChatGPT or Claude sign-in directly from the provider selector; after the local session is recognized, the chosen provider is selected. User-facing connection messages no longer expose internal token or repository diagnostics.
- El callback OAuth de ChatGPT admite el retorno local del navegador con un `state` pendiente, sin abrir las demás rutas de la API al exterior; al completarse confirma la conexión y el selector de Umbral se actualiza automáticamente.
- El selector de modelos de ChatGPT queda accesible por encima del modal de cuentas en escritorio y móvil; tras OAuth espera a que haya un modelo elegido para activar ChatGPT y muestra los avisos del asistente como toasts temporales.
- La portada adopta la estructura editorial de Umbral Mega con la identidad amarilla de Umbral, cifras del snapshot activo, carrusel accesible, promesas interactivas, preguntas frecuentes y llamadas a la agenda.
- La cinta de categorías de la portada repite copias medidas y avanza a velocidad constante; espera a cubrir el ancho visible antes de moverse y respeta el movimiento reducido.
- Los tooltips propios se cierran al salir el puntero, al perder foco la ventana o al ocultarse la aplicación, incluso si falta el evento `pointerleave`.

### Documentation

- Registra la prueba real de instalación y actualización de la app de escritorio mediante GitHub Releases.

## [0.1.1] — 2026-10-08

### Changed

- El aviso de escritorio muestra la versión de destino mientras descarga una actualización.

## [0.1.0] — 2026-10-08

### Added

- Actualizaciones de Umbral Desktop desde GitHub Releases: descarga estable en segundo plano, aviso integrado con reinicio voluntario y workflow Windows que publica el instalador, metadatos de Electron y SHA-256 al crear un tag de versión coincidente.
- Floating comic-style motion control with system, reduced, and full modes; the web browser and desktop app save independent preferences.
- Public web mode without accounts: drafts, versions, reviews, impact notes and weights are stored in each browser's IndexedDB, with portable JSON copy/restore and Markdown export.
- Stateless public API under `/api/v1/public` (agenda, topic, queries, drafts, validation), with a global Gemini quota of 20 calls per UTC day (retries included) and a citation-backed template as fallback.
- Daily snapshot feed (`data/current.json` plus the last seven valid snapshots) that the API and the desktop app download only when it changes, verifying SHA-256 and keeping the last valid snapshot on failure.
- Windows desktop app (Electron + NSIS, per-user) bundling the API, the pipeline, PyTorch CPU and the pinned Laya weights; offline reclassification in a separate process.
- Local Laya calibration workflow for headline classification: agent-review provenance, full-precision logits, model-bound temperature and threshold profiles, an untouched-test gate, and shared web/desktop profile packaging.
- Local preparation and cache verification for a calibrated Laya artifact, bound to the fixed review labels, base snapshot, split hashes, and test gate.
- Hosted verification can require an exact Laya model version, calibration profile, and profile hash from the API's active snapshot.
- Production workflows can prepare and verify the calibrated artifact, promote a changed versioned snapshot, and gate hosted rollout on the exact model and profile identity; the daily workflow remains disabled by default.
- Calibrated Laya snapshot `20261007-e704e952` with 991 real headlines, preserved raw logits, and the baseline snapshot retained for rollback.
- Desktop app: the native Windows title bar is replaced by a comic-style one (minimize, maximize/restore, close; drag area, custom tooltips, keyboard and 44 px targets) on the startup screen and in the app. The window is frameless; its controls go through a restricted IPC channel limited to the app origin and the startup page.
- Custom, keyboard-accessible controls replacing every native browser control, with a static guard and end-to-end tests.
- Floating evidence assistant with compact and expanded layouts, minimized dock, scope-aware independent questions, readable citations and query metadata, retry/edit states, response copy, and per-identity IndexedDB conversation history.
- Assistant: in-flight queries can be cancelled (a real `AbortSignal` through the HTTP, browser-workspace and mock API layers), completion/cancellation is announced to screen readers, and editing a failed question asks before replacing an unsent draft.
- Local model selection: Borradores and the evidence assistant show only connected and available providers, support ChatGPT OAuth and the existing Claude CLI subscription session, retain the assistant choice per identity, and explain when a provider becomes unavailable. No automatic switch to another personal account is made.
- Assistant model picker: the provider and active model now have a dedicated, full-width control, while account management is a separate action; the option list remains legible on narrow desktop panels.
- Assistant sources: answers now cite with numbered markers (`[1]`, `[2]`…) instead of raw evidence ids; each marker is a keyboard-accessible button that opens and focuses the matching source. Each source shows its cited passage (with the matched terms highlighted), sources excluded for containing agent-directed instructions are listed without their text, and every answer states that it comes from rules over sources, not an AI model.
- Assistant retrieval: economic questions no longer abstain because of ordinary verbs or adjectives ("creció", "alta", "según"). Only unlinkable entities introduced by a preposition or a capital letter ("de Marte", "según el FMI") cause an abstention. Natural synonyms ("habitantes", "la economía creció"), year ranges ("entre 2021 y 2023"), an explicit note when no country was named (Panama is assumed), a statement of which query terms are covered or unsupported in partial answers, and a guard that reports the figure without presenting an annual aggregate as proof of a claim. The agenda is only computed for agenda questions.
- Assistant follow-ups: `POST /queries` accepts an optional `followUp` (the previous answer's `followUpContext`: snapshot, intent, topic/evidence ids, countries, indicators and years — identifiers only, never text) and returns `resolvedQuestion`, `followUpContext` and `followUpSuggestions`. Elliptical questions ("¿Y en Colombia?", "¿Y la inflación?", "¿Qué falta verificar del primero?", "¿Cuáles son las fuentes del segundo?") are resolved by rules; self-contained questions ignore the context and unresolvable ones ask for clarification instead of guessing. The panel offers follow-up chips and a "continue with the previous context" switch.
- Assistant unread indicator: a response that arrives while you are not looking at that conversation (panel closed, minimized or in the history view) is stored as unread, shown as a count on the header button and the dock, announced to screen readers, and cleared when you view it — it also survives a reload.
- Assistant tabs: a change in another tab now reloads only the affected conversation (the message carries its id) instead of the whole history; a local query in flight or an unsaved local draft is never overwritten. The panel was split into focused modules (`components/assistant/`: answer card, turn, composer, history view and two hooks).
- Optional AI composition of assistant answers: `POST /queries/compose` (and `/public/queries/compose`) lets Gemini (Free Tier, no paid fallback) rewrite an answer that already has sources as short natural-language statements using only those sources. Code validates every statement (evidence ids, fields, literal passages, figures, instructions, secrets; one corrective retry) and any failure keeps the rules-and-sources answer with the reason. It never runs by default, skips abstentions and contradictions, counts against the shared daily Gemini quota (identical public results are reused), and the panel labels the origin ("Redactada con IA… verificada por código" vs "Reglas y fuentes · sin modelo de IA") and keeps the rules answer one click away.
- Evaluation extension (`eval/dev/benchmark_dev_ext.jsonl`, 48 development probes: natural wordings, follow-up chains, unlinkable entities, paraphrased/multilingual/obfuscated/homoglyph injections) and a runner that chains follow-ups and checks per-case structural expectations. Findings fixed: population and other large values were shown as `4.51558e+06` (digits lost) and are now written in full (`fmt_value`); an indicator named only as a unit ("% del PIB", "% de la población") no longer adds an unrequested indicator to the answer; the jailbreak pattern `DAN` matched the Spanish verb "dan" and masked 4 real headlines as untrusted; and the instruction detector now folds homoglyphs and spaced letters and recognises more families. Before/after results are kept in `eval/results/` (in-sample; the reserved benchmark was not read).
- `ComposeResponse.attempts` (model calls made per composition) and `eval/run_compose_eval.py`, which measures the AI composition against real Gemini inside a hard call budget. First real measurement (10 development queries, 11 calls, `gemini-3.1-flash-lite`): 10/10 passed code validation, 9/10 at the first attempt; a reading of the outputs found 2/10 that passed but lost information (agenda scores and attribution; a verification checklist replaced by the headline), so human review of support is still pending.
- AI composition now keeps the kind of answer: code requires every headline to be attributed to its outlet, each agenda topic to carry its score (a special `reglas` evidence with `nota_N`/`pendiente_N` fields), every agenda topic to be covered, and a verification list to cite the pending items instead of restating the headline; the prompt also receives the answer type. Re-measured with real Gemini on the same 10 queries: 8/10 accepted (7 at the first attempt, 1 after the retry), the 2 other cases fell back to the rules answer on a 30 s Gemini read timeout; the two answers that had lost information now keep it (agent reading, in-sample, not human review).
- Assistant history: stored records carry a schema version and are validated on read (a malformed answer becomes a retryable error instead of breaking the panel), at most 50 conversations per identity are kept, old deletion markers are purged after 30 days, and copy and Markdown export share one serializer that includes cited passages.
- `deployCommit` in `GET /api/v1/health` (from `UMBRAL_DEPLOY_COMMIT` or Render's `RENDER_GIT_COMMIT`) so a deployment can be verified before publishing the web app.
- `UMBRAL_CORS_PREVIEW_PROJECT` to allow only the Firebase Hosting preview channels (`<project>--pr-<n>-<hash>`) of one project.
- Publication checks: `scripts/check_public_files.py` (publishable files only, no personal paths, no AI-tool credits, no broken links, commit messages) and `scripts/wait_for_deploy.py`.
- GitHub Actions: per-PR Firebase Hosting previews and a single deployment orchestrator (Render, verification, Hosting, online check); a scheduled daily data workflow, disabled until explicitly enabled.
- First hosted deployment: API on Render Free and web on Firebase Hosting, verified end to end by `scripts/verify_hosted.py`.
- English and Spanish READMEs, a security policy and public architecture, deployment and validation guides.

### Changed

- Refined the responsive web layout with evenly aligned agenda cards and scores, equal-width action groups, floating assistant and classification-warning panels, and matched page headers across views.
- Render Blueprint pins Python `3.12.14` and `uv==0.12.7`, disables automatic deploys and receives each deployment through a secret hook with the exact commit.
- Sanitised the development reports under `eval/` so they no longer contain machine-specific paths.

### Security

- Private agent instructions, coordination notes, hand-off documents, task boards, prompts and internal logs are excluded from the repository by an explicit Markdown allowlist, enforced in CI even for force-added files.

### Known limits

- The current data snapshot is provisional and classification, claim support and Precision@5 await human review.
- Hosted deployment, the daily workflow and the Windows installer have not been verified end to end on clean machines yet; see `docs/public/VALIDATION.md` for what has actually been run.
