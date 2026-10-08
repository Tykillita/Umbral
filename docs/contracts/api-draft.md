# Contrato de la API de Umbral (`api-draft`, v0.3.1 + integración de pesos versionados, ediciones inmutables y conexión ChatGPT)

Propietario: API (`apps/api`). Fuente de verdad técnica: **`apps/api/openapi.json`** (se regenera con `cd apps/api && uv run python scripts/export_openapi.py`; `--check` falla si está desactualizado). Este documento explica la semántica que el esquema no expresa.
Consumidores: `frontend` (tipos TS con `openapi-typescript`), `calidad` (pruebas T01–T10, CI).

Estado: **v0.2.0, ya servido con datos reales del snapshot del pipeline** (`data/snapshots/CURRENT`). Cambios 0.1→0.2 (aditivos): `validation.factualCitationCoverage`, titulares con instrucciones enmascarados como `[texto con instrucciones omitido]` en textos generados, stub de Gemini por entorno. Cambios aditivos en 0.x/1.x; cualquier cambio rompedor se avisa por mensaje + línea `contrato` en `docs/board/events.log`.

## 1. Convenciones

- Base: `/api/v1`. JSON **camelCase**. Fechas ISO 8601 UTC con `Z`; la UI convierte a `America/Panama`.
- Todas las respuestas de datos llevan `snapshotId`, `rulesVersion` (y `dataMode`: `fixture` | `provisional` | `congelado`). **Si `dataMode == "fixture"` la UI debe mostrarlo.**
- Los campos con valor por defecto **siempre** aparecen en las respuestas (marcados `required` en el esquema).
- Errores: `{ "code": "...", "message": "...", "details": {...}|null }` con estado HTTP 401/403/404/409/422/429/503. Los errores 422 de validación de entrada de FastAPI mantienen su forma estándar (`detail: [...]`).
- Auth: local = sesión de usuario único (sin cabeceras). Web = `Authorization: Bearer <ID token de Firebase Auth anónima>`. Modo de pruebas `UMBRAL_AUTH_MODE=dev-header` = cabecera `X-Umbral-User: <id>`. Cada usuario tiene su propio espacio de casos/borradores/impactos. 429 incluye cabecera `Retry-After`.
- Enumeraciones (slugs ASCII estables; las etiquetas en español vienen en campos `*Label`):
  - `category`: `economia | logistica_canal | turismo | servicios_publicos | eventos_naturales | regulacion | indeterminado`
  - `geoRelevance`: `panama | regional | none | indeterminate` (igual que el snapshot)
  - `evidenceStatus`: `insuficiente | parcial | suficiente` (**independiente del puntaje**)
  - `band`: `bajo [0,40) | medio [40,70) | alto [70,100]`
  - `reviewStatus`: `nuevo | en_revision | requiere_evidencia | aprobado_como_borrador | descartado`
  - `generationMode`: `modelo | recuperado | plantilla` (siempre mostrar `generationLabel`)
  - `claim.type`: `hecho | declaracion | inferencia | hipotesis`
  - `answerStatus`: `respondida | parcial | contradiccion | abstencion`

## 2. Endpoints

| Método y ruta | Descripción |
|---|---|
| `GET /health` | Estado, versión de datos (`snapshotId`, `dataMode`, `provisional`, `containsFixtures`, `classifier`), integridad (manifest SHA-256, hash de predicciones de Laya), modos (`offline`, `localMode`, `persistence`, `authMode`), estado de proveedores de redacción. |
| `GET /rules` | Reglas `scoring-v1`, pesos, bandas y changelog. |
| `GET /snapshot` | «Fuentes y evaluación»: manifest, `qualityReport`, catálogo de fuentes (`sources`), `metrics` (nulo si no hay ejecución real), integridad. |
| `GET /topics` | Agenda ordenada por puntaje (desempate: urgencia ↓, luego ID ↑). Query: `limit` (def. 5), `category`, `evidence`, `band`, `reviewStatus`, `q` (BM25+RapidFuzz sobre temas), `includeComponents` (def. true). `items[].rank` es la posición en el resultado filtrado. |
| `GET /topics/{topicId}` | Ficha: qué se reporta, quién (`reporters`, original/réplica), `articles` con procedencia y fechas, contexto oficial (`officialContext`, con unidad/año/limitaciones), afirmaciones respaldadas (`supportedClaims`), verificaciones pendientes, contradicciones, `score` desglosado (componentes con regla, justificación y **límites**), `impact` (propuesta automática o asignación editorial), `evidence` (estado, vacíos, confirmación del revisor), `recommendedAction`, `warnings`, y `case` (estado de revisión del usuario). |
| `PUT /topics/{topicId}/impact` | Asignación editorial de impacto: `{expectedVersion, level, justification (≥20 car.), evidenceIds (≥1), author, reason}`. Conserva motivo y versión; recalcula el puntaje. |
| `POST /queries` | `{question, topicId?, limit?}` → respuesta con citas o **abstención** (`answerStatus: "abstencion"`, `abstentionReason`, `missing`). Incluye `hits` (bm25/fuzzy), `contradictions` visibles y `retrieval` (cobertura de términos). Respuestas económicas incluyen hits de los indicadores realmente seleccionados/citados; años futuros exigen mención explícita en titulares pertinentes (sin predecir resultados). |
| `POST /topics/{topicId}/drafts` | Cuerpo opcional `{provider: auto|gemini|recuperado|plantilla|chatgpt|claude}`. Devuelve `DraftResponse {case, draft, notices}`. `draft.generationMode`/`generationLabel` indican modelo / recuperado / plantilla; `fallbackReason` + `fallbackDetail` explican por qué se cayó a otro modo (`cuota_agotada`, `limite_por_usuario`, `modo_sin_conexion`, `proveedor_no_disponible`, `proveedor_no_conectado`, `sin_credenciales`, `validacion_fallida`, `solo_localhost`, `solicitado`). `draft.validation` informa IDs de cita, alcance, formato y límites de palabras. |
| `GET /cases/{caseId}` | Caso del usuario (`caseId = "case-" + topicId`). Si aún no existe devuelve `persisted:false, version:0, status:"nuevo"`. |
| `PUT /cases/{caseId}/draft` | Guardar edición humana del borrador vigente (brief, guion, copy, preguntas, afirmaciones). Requiere `expectedVersion` (409 si difiere). Se re-valida el borrador y se anota `editedBy`. |
| `PATCH /cases/{caseId}/review` | `{expectedVersion, status, reviewer, comment?, evidenceConfirmed?}`. Máquina de estados y reglas en §3. 409 si `expectedVersion` ≠ versión actual. |
| `GET /cases/{caseId}/export` | JSON `{filename, markdown, …}`; con `?format=markdown` devuelve `text/markdown` descargable. Markdown listo para pegar en Notion. |

## 3. Revisión y concurrencia

- Un **caso** es el trabajo de un usuario sobre un tema. Se crea al primer borrador, revisión o asignación de impacto. `version` empieza en 0 (no persistido) y sube +1 con cada cambio (borrador, edición, revisión, impacto). **Toda escritura exige `expectedVersion`**; si no coincide → `409 conflicto_de_version` con `details.currentVersion`.
- Transiciones permitidas (`allowedTransitions` en `CaseView`):
  `nuevo → en_revision`; `en_revision → requiere_evidencia | aprobado_como_borrador | descartado`; `requiere_evidencia → en_revision | descartado`; `aprobado_como_borrador → en_revision`; `descartado → en_revision`. Otra transición → `422 transicion_invalida`.
- `reviewer` (persona responsable) obligatorio; `comment` obligatorio para `requiere_evidencia` y `descartado`.
- **No se puede aprobar como borrador** si no existe borrador, si la evidencia del sistema es `insuficiente` salvo que el revisor la confirme (`evidenceConfirmed: true`) con comentario, o si hay una fuente sospechosa sin revisar (se pide comentario). Aprobar un borrador **no es publicar**.
- `history[]` conserva cada evento (versión, actor, de→a, comentario).

## 4. Puntaje `scoring-v1` (resumen; ver `GET /rules`)

`P = 30R + 25I + 20U + 15N + 10E`. R: Panamá 1 / regional 0,5 / sin relación o indeterminada 0. I: bajo 0,25 / medio 0,5 / alto 1 (asignación editorial; si no hay, **propuesta automática** marcada `origin: propuesta_automatica` que requiere confirmación). U (contra `cutoffUtc` del snapshot): publicación original ≤24 h → 1; ≤7 d → 0,5; antes o **fecha de publicación desconocida** → 0 (con límite visible). N: evento nuevo 1; recirculación 0 (los duplicados conservan el puntaje del evento). E: sin procedencia 0; una 0,33; dos independientes 0,67; fuente primaria pertinente + cobertura original 1. Cada `ScoreComponent` trae `rule`, `justification` y `limits`.

## 5. Notas para el frontend

- Mostrar siempre: `snapshotId`, `rulesVersion`, `dataMode`, banner «basado únicamente en titular/metadatos» (`headlineOnly`/`headlineOnlyNotice`), `generationLabel` del borrador, y `needsInvestigation` (prioridad alta + evidencia insuficiente: «requiere investigación, no habilita publicación»).
- `articles[].suspiciousInstructions == true`: marcar la fuente como «contenido no confiable (contiene instrucciones)». El backend nunca las ejecuta.
- `IndicatorPoint.note` ya contiene la limitación «dato anual de AAAA, no una medición de hoy».
- El guion se estima a ~2,5 palabras/s (45–60 s ≈ 112–150 palabras); el límite se valida en `draft.validation`.
- `claims[].citations[]` = `{evidenceId, field, passage}`; `evidenceId` puede ser de un artículo (`art_…`), un indicador (`ind_…`).

## 6. Validación del borrador y métrica oficial de citas

- `draft.validation.citationCoverage`: afirmaciones con cita válida / todas las propuestas (incluye inferencias e hipótesis; informativo).
- **`draft.validation.factualCitationCoverage`**: métrica oficial del PDF §9 (meta 100 %): afirmaciones **factuales** (`hecho` + `declaracion`) con cita válida / propuestas; `null` si no se propuso ninguna. Las afirmaciones inválidas (ID inexistente, campo inexistente, pasaje que no está en el campo, cifra que no aparece en lo citado, fuente con instrucciones) se **rechazan** y no se muestran (`rejectedClaimIds`).
- Si el modelo produce un borrador inválido, el servicio cae a «recuperado» o «plantilla» con `fallbackReason: validacion_fallida`.
- Un titular de fuente con instrucciones (T07) nunca se reproduce en título/brief/guion/copy/respuestas: se sustituye por `[texto con instrucciones omitido]`; la fuente sigue visible en `articles[]` con `suspiciousInstructions: true` para auditoría y no es citable.

## 7. Modos, persistencia y adaptadores

- **Orden de redacción (`provider: auto`)**: Gemini (Free Tier, `GEMINI_MODEL`, por defecto `gemini-3.1-flash-lite` tras prueba editorial real; límite diario por usuario `GEMINI_CALLS_PER_USER_DAY`) → borrador **recuperado** → **plantilla** con citas. `GEMINI_FALLBACK_MODEL` vacío por defecto, solo se habilita explícitamente otro del mismo Free Tier. Nunca se cambia a un proveedor de pago. Con `UMBRAL_OFFLINE=1` no se hace ninguna llamada externa.
- **ChatGPT (OAuth) y Claude (CLI)**: las conexiones personales y sus sesiones solo están disponibles en localhost. El estado de `/health` muestra cuenta y disponibilidad; el selector ofrece cada proveedor solo con sesión y modelo disponibles. Si una selección deja de estar disponible, la interfaz vuelve a Gemini y lo explica; nunca cambia a otra cuenta personal automáticamente. La generación usa la conexión elegida y, si no está conectada o falla, cae a recuperado/plantilla con el motivo correspondiente.
  - ChatGPT: `GET /connections/chatgpt` reconoce los perfiles locales. `POST /connections/chatgpt/start` inicia el flujo OAuth oficial con PKCE; el callback valida state, nonce e identidad firmada, y guarda tokens fuera del repo con DPAPI en Windows o permisos 0600 en Unix. `/connections/chatgpt/models` y `PUT /connections/chatgpt/model` exponen y fijan el modelo de la cuenta. La inferencia usa Responses API con `store:false`, `stream:true` y acepta solo `response.completed`; los tokens no se devuelven a la UI. OAuth e inferencia con cuentas reales requieren una sesión del usuario y no se consideran verificadas por pruebas simuladas.
  - Claude: instala el CLI oficial (`claude`). `GET /connections/claude` detecta la sesión local con `claude auth status --json`; `POST /connections/claude/login` lanza `claude auth login --claudeai` y logout usa `claude auth logout`. La generación usa print JSON con `--json-schema`, sin herramientas ni MCP, con prompt por stdin y sin shell. El entorno del CLI elimina `ANTHROPIC_API_KEY` y `ANTHROPIC_AUTH_TOKEN`, y rechaza sesiones de Consola/API para evitar facturación por uso. No se usa `--bare`, porque impide utilizar la sesión OAuth del CLI. El CLI y una sesión real no se ejecutaron durante las pruebas.
- **Stub de pruebas** `UMBRAL_GEMINI_STUB=ok|quota|down|no_key`: reemplaza a Gemini por un proveedor simulado (modelo `gemini-stub`, rótulo en `/health.notes`). Respeta `UMBRAL_OFFLINE`; prohibido con `UMBRAL_AUTH_MODE=firebase`.
- **Persistencia**: `sqlite` (local, `UMBRAL_SQLITE_PATH`) | `firestore` (`FIREBASE_PROJECT_ID`, credenciales de la cuenta de servicio solo por entorno/servidor) | `memory` (pruebas). Si Firestore no puede inicializarse, el arranque falla con diagnóstico seguro; nunca se cambia a SQLite de forma implícita. Misma interfaz (`storage.Repository`), escrituras compare-and-swap por `version`.
- **Auth web**: configuración obligatoria `UMBRAL_LOCAL_MODE=0`, `UMBRAL_AUTH_MODE=firebase`, `UMBRAL_PERSISTENCE=firestore` y `FIREBASE_PROJECT_ID`. El arranque rechaza combinaciones inseguras. `firebase-admin` verifica ID token con app propia del proyecto y revocación (`check_revoked=True`). Los modos local/dev-header también rechazan clientes remotos. Auth/Firestore reales pendientes (sin credenciales); pruebas de guardas y llamadas SDK simuladas identificadas como tales.
- **Gemini**: un intento SDK por modelo, sin reintentos internos; 429 y credenciales inválidas son terminales, 400 de esquema activa `validacion_fallida` sin probar otro modelo. Solo 404/5xx/errores de red pueden probar el respaldo configurado. La serialización real del SDK se verificó con transporte HTTP reemplazado, sin claves reales ni consumo de cuota.

## 8. Alcance temático de la agenda (v0.3.0, aditivo)

- `GET /topics?scope=in_scope|all` (defecto **`in_scope`**): excluye los temas de `category == "indeterminado"` (el clasificador no los asigna a ninguna de las seis categorías del reto: **fuera del alcance temático**). La fórmula `scoring-v1`, el ranking y el desempate **no cambian**; `rank` se numera sobre los temas visibles.
- Respuesta: `scope`, **`outOfScopeCount`** (cuántos quedan ocultos con el resto de filtros aplicados; 0 con `scope=all`) y por tema `category` + **`outOfScope`** (bool). El interruptor de la UI «Mostrar fuera de alcance (N)» usa `scope=all` y `outOfScopeCount`.
- Con `category=indeterminado` explícito se muestran siempre. `q` + `scope=in_scope` no devuelve temas ocultos (usa `scope=all`).
- Los temas ocultos siguen accesibles por ID (`GET /topics/{id}`, con `summary.outOfScope=true` y un aviso en `warnings`), por `POST /queries` y por exportación; no se pierde trazabilidad. La consulta de agenda («¿qué cinco temas…?») usa solo `in_scope`.
- Impacto `I` automático: la categoría del clasificador (sin calibrar) ya **no** suma «alcance público amplio» por sí sola; solo cuenta si hay corroboración (≥2 procedencias independientes o serie oficial vinculada). La justificación lo dice («no suma por sí sola»). Sigue siendo una propuesta que requiere confirmación editorial.
- `GEMINI_THINKING_BUDGET` (opcional) y un único reintento del modelo con la retroalimentación de la validación si el borrador sale fuera de los límites (cuenta contra el límite por usuario).

## 9. Explicación de R y trazabilidad del impacto (v0.3.1, aditivo)

- `TopicSummary.relevanceReason` (tarjeta y ficha, también con `includeComponents=false`) y el componente `R` de `score.components` explican **por qué R vale lo que vale**: regla aplicada (Panamá 1 / regional 0,5 / sin relación o indeterminada 0), titular que la justifica con su ID y la evidencia del clasificador (`EvidenceArticle.geoEvidence`, p. ej. `laya:panama=0.669`). Si la probabilidad es < 0,70 se añade el límite «Evidencia débil… puede ser un falso positivo».
- R **no se edita** en la API (la fórmula y las reglas de `scoring-v1` no cambian): un falso positivo se corrige en el pipeline (`predictions`) o se descarta el caso con comentario.
- `PUT /topics/{id}/impact` exige `reason` (≥3 car. no vacíos), `justification` (≥20), `evidenceIds` (≥1, del propio tema), `author` y `expectedVersion`; cada cambio sube `version`, queda en `history` (kind `impacto`, actor, motivo) y en `impact.version`; versión desfasada → 409.
- Modelo de redacción: por defecto `gemini-3.1-flash-lite` (validado). `gemini-flash-lite-latest` es opción por `GEMINI_MODEL` (≈7 s vs ≈15 s medidos) con el riesgo del alias móvil. Ante validación fallida del modelo se reintenta **una vez** con la retroalimentación; si vuelve a fallar, o ante cuota/caída/offline, se cae a recuperado y luego a **plantilla** con citas.

## 10. Alcance de E: contexto oficial vs fuente primaria; contenido patrocinado (v0.3.1, aditivo)

- **Nota de versión.** `info.version` de OpenAPI = 0.3.1. Cambia el cálculo de `E` y del estado de evidencia (la fórmula `scoring-v1` y sus pesos no cambian).
- Una **serie oficial vinculada por palabra clave/tema** (`officialContext.indicators`) es solo **contexto oficial**: se sigue mostrando con sus límites, pero **no eleva E ni el estado** y ya no suma en el impacto automático. `E` se calcula por procedencias independientes (0 / 0,33 / 0,67); solo llega a **1,0** si un revisor **confirma una fuente primaria pertinente** que respalde ese hecho (y hay cobertura original).
- `PATCH /cases/{id}/review` acepta `primarySourceConfirmed: true|false` (con `comment` obligatorio: motivo y fuente). Se guarda por usuario/caso (`CaseView.primarySourceConfirmed/By/Reason`) y se refleja en `evidence.primarySourceLinked` (ahora = confirmada), `E`, el estado y `needsInvestigation`. `evidence.officialContextLinked` indica que hay serie vinculada (contexto).
- Estado **suficiente**: ≥2 procedencias independientes con fuente primaria confirmada, o ≥3 procedencias independientes; sin contradicciones y con fecha de publicación original conocida. Insuficiente: <2 procedencias y sin fuente primaria confirmada.
- **Contenido patrocinado**: URL con `/publirreportajes/`, `/publireportaje/`, `/patrocinado/`, `/sponsored/`, `/branded-content/` → `EvidenceArticle.sponsoredContent`, `TopicSummary.possibleSponsored`, `evidence.possibleSponsored`, aviso en `warnings` y gap `contenido_patrocinado`. No cuenta como procedencia independiente; si todo el tema es patrocinado, **E ≤ 0,33**, estado insuficiente y ni una fuente primaria confirmada lo eleva. La UI debe mostrar «posible contenido patrocinado».
- Impacto automático (`I`): 3 factores (relación con Panamá, ≥2 procedencias independientes, categoría amplia con ≥2 procedencias). La categoría del clasificador y las series vinculadas por palabra clave no suman por sí solas.
- Las respuestas de `POST /queries` informan el estado del sistema (sin confirmaciones de revisor).

## 11. Integración posterior (verificada contra `openapi.json` real; 194 pruebas + 1 omitida sin extra `firebase`)

Cambios incorporados por otras sesiones; el contrato vigente es `apps/api/openapi.json` (info.version 0.3.1):
- **`GET /rules` / `PUT /rules`**: pesos de `scoring-v1` editables por usuario, con `expectedVersion`, `weights` (R, I, U, N, E enteros 0–100 que suman 100), `reason` (≥3 car.) y `author`; cada cambio crea una revisión (`version`, `history[]`, `rulesVersion` = `scoring-v2`, `-v3`…) y el puntaje de ese usuario se recalcula; versión desfasada → 409. Las reglas de cada componente (E, sponsored, etc.) no cambian.
- **Ediciones de borrador inmutables**: `PUT /cases/{id}/draft` ya no sobrescribe: crea un **nuevo** `DraftRecord` (`number` +1, nuevo `draftId`, `previousDraftId` con el anterior, `editedBy/editedAt`, `rulesVersion` vigente) y el caso sube de versión. `CaseView.drafts` conserva todas las versiones y `currentDraft` es la última.
- **Conexión personal ChatGPT (solo localhost)**: `GET /connections/chatgpt`, `POST /connections/chatgpt/start`, `GET /auth/callback`, `POST /connections/chatgpt/select`, `GET /connections/chatgpt/models`, `PUT /connections/chatgpt/model`, `DELETE /connections/chatgpt/{profileId}`. Mantenido por otra sesión (Codex; ver `docs/CODEX-GOAL-CHATGPT.md`); su detalle no se duplica aquí.
- **Conexión personal Claude (solo localhost)**: `GET /connections/claude`, `POST /connections/claude/login` y `POST /connections/claude/logout`. Detecta y usa la sesión de suscripción del CLI oficial; nunca lee credenciales de consola ni hereda claves de API en el proceso de generación.
- **Firebase/Firestore**: la auth web (`UMBRAL_AUTH_MODE=firebase`) y la persistencia Firestore están verificadas con emuladores reales por la sesión de verificación Firebase (no con proyecto de nube).
- Lo ya documentado sigue vigente: alcance temático (§8), explicación de R (§9) y E/fuente primaria confirmada/contenido patrocinado (§10); sus pruebas (`test_evidence_scope.py`, `test_scoring.py`, `test_api.py`) siguen verdes tras la integración.
