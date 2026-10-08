# Contrato de `data-testid` para las pruebas E2E (propuesta de `calidad` a `frontend`)

Los E2E (Playwright, `tests/e2e/`) localizan elementos solo con `data-testid`. Si cambias un nombre, avisa a `calidad`.
Donde se indica `[attr]`, el atributo lleva el dato para poder verificarlo sin depender del texto.

| Zona | testid | Contenido / atributos |
|---|---|---|
| Global | `app-root` | raíz de la isla React en `/app` |
| | `snapshot-badge` | muestra el `snapshotId` real servido por la API |
| | `data-mode-banner` | aviso si `dataMode` = fixture/provisional; `[data-mode]` |
| | `offline-indicator` | visible cuando `health.offline` es true |
| | `mock-banner` | **solo** si el frontend usa datos de demostración (debe estar ausente en E2E) |
| Navegación | `nav-agenda`, `nav-borradores`, `nav-fuentes` | |
| Agenda | `agenda-list` | contenedor |
| | `topic-card` | una por tema; `[data-topic-id]`, `[data-band]`, `[data-evidence]` |
| | `topic-score`, `topic-band`, `topic-evidence-status` | dentro de la tarjeta |
| | `topic-needs-investigation` | visible si `needsInvestigation` |
| | `agenda-search` (input), `filter-category`, `filter-evidence`, `filter-band` | |
| Ficha | `ficha` | contenedor; `[data-topic-id]` |
| | `ficha-reported` | «qué se reporta» |
| | `score-component-R` … `score-component-E` | valor, regla y límites del componente |
| | `evidence-status` | estado de evidencia; `[data-status]` |
| | `source-item` | por artículo; `[data-evidence-id]`; fecha publicación y detección separadas |
| | `source-untrusted-badge` | «contenido no confiable» (T07) |
| | `contradiction` | por contradicción; muestra todas las versiones |
| | `pending-verification` | por verificación pendiente |
| | `official-indicator` | `[data-year]`, `[data-unit]`, `[data-country]` |
| | `headline-only-notice` | «basado únicamente en titular/metadatos» |
| | `recirculation-notice` | fecha original visible (T03) |
| Asistente | `assistant-input`, `assistant-send` | |
| | `assistant-answer`; `[data-status]` = `respondida|parcial|contradiccion|abstencion` | |
| | `assistant-citation` | `[data-evidence-id]` (enlace a la fuente) |
| Borradores | `draft-generate` | botón (admite elegir proveedor: `draft-provider`) |
| | `draft-origin-label` | «Generado por un modelo / Recuperado… / Construido mediante plantilla»; `[data-mode]` |
| | `draft-fallback-reason` | motivo del fallback si lo hay |
| | `draft-brief`, `draft-script`, `draft-copy`, `draft-title` | textos editables |
| | `draft-claim` | `[data-claim-type]`; `draft-claim-citation` `[data-evidence-id]` |
| | `draft-save` | guardar edición |
| | `draft-validation` | resultado de validación y cobertura de citas |
| Revisión | `review-reviewer` (input), `review-comment` (textarea) | |
| | `review-action-en_revision`, `review-action-requiere_evidencia`, `review-action-aprobado_como_borrador`, `review-action-descartado` | botones |
| | `review-status` | estado actual; `[data-status]`, `[data-version]` |
| | `review-conflict` | aviso de conflicto de versión (409) |
| | `review-history` | historial |
| | `export-markdown` | botón de exportación a Notion |
| Fuentes | `sources-snapshot-id`, `quality-report`, `sources-catalog`, `metrics-table`, `integrity-status` | |
