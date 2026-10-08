# Contrato del snapshot de datos (`snapshot-schema` v1.1.0)

Adición v1.1.0: `calibrationLogits`, `calibratedProbabilities` y `calibrationProfileId` para conservar logits precisos, probabilidades ajustadas y la identidad del perfil Laya. `probabilities` sigue siendo la salida cruda del checkpoint. La aplicación web consume el snapshot generado por el pipeline; la app empaquetada usa el mismo perfil al reclasificar sin conexión. Adición v1.0.3: `origin.source=tvn_news_sitemap` y `publishedAtBasis=news_sitemap_publication`, para metadatos del sitemap Google News oficial declarado en robots.txt/índice TVN. `news:publication_date` es publicación; nunca se usa `lastmod` como publicación. No se guardan imágenes/cuerpos. Al fusionar raws, la ventana se limita a 90 días reales respecto al nuevo corte. `build --no-set-current` deja candidatos sin activar.

Propietario: pipeline (`pipeline/`). Consumidores: API (carga y servicio), pruebas (T01–T10, CI) e interfaz web (vía API). Cambios de contrato: `schemaVersion` + aviso por mensaje + línea `contrato` en `docs/board/events.log`.

Estado: **v1.1.0** (1.0.3 = metadatos de publicación del sitemap TVN; 1.0.2 = `geoRelevance` por contenido + `geoMethod` + `geoLayaRaw`; `independentProvenanceCount` también colapsa titulares contenidos íntegros en otro; `manifest.classifier.scopeMethod`. 1.0.1 = solo campos añadidos y aclaraciones: `urlVariantsSeen`, `ambiguousCandidateIds`, `contradictionCandidateIds`, indicadores fixture, 540 filas, `effectiveDate`, claves de `probabilities`). Los campos marcados *(opcional)* pueden faltar; el resto siempre existe (con `null` explícito cuando el valor es desconocido). Si algo cambia lo haré de forma **aditiva** (nuevos campos); no renombraré ni quitaré campos dentro de 1.x.

## 1. Reglas generales

- Codificación UTF-8, LF, un objeto JSON por línea en `*.jsonl`. Claves en **camelCase** (igual que la API). Los CSV de compatibilidad con el PDF usan los nombres en español del PDF §7.
- Fechas/horas: ISO 8601 **UTC con sufijo `Z`** (`2026-10-07T00:21:09Z`). Nunca hora local en datos; la hora de Panamá (`America/Panama`, UTC−5) se aplica solo al mostrar. Un año es un entero (`2024`).
- Nulos: se conservan como `null`. **Nunca** se rellena con 0 ni cadena vacía.
- Los textos de noticias son **datos no confiables** (T07): pueden contener instrucciones; nunca se interpretan.
- Todo registro tiene `dataOrigin`: `"real"` (descargado de la fuente) o `"fixture"` (sintético, claramente etiquetado, `articleId`/`indicatorId` con prefijo `fx_`). Un snapshot con cualquier fixture lleva `manifest.containsFixtures = true`.
- Snapshot provisional: `manifest.provisional = true` mientras no exista un paquete oficial congelado de la organización (PDF §6), haya fixtures o faltantes de cobertura; los motivos van en `manifest.provisionalReasons`. **La ventana de fechas del PDF ya NO es motivo** (decisión del usuario: se ignora el intervalo 2024-01-01..2025-10-01; ventana = 30 días previos a la extracción, ampliable a 90; corte = fecha de extracción).
- `snapshotId = YYYYMMDD-<hash8>`; `YYYYMMDD` = fecha del corte UTC; `hash8` = primeros 8 hex de SHA-256 de la cadena `sha256(articles.jsonl)+sha256(indicators.jsonl)+sha256(predictions.jsonl)+sha256(clusters.jsonl)` (hex concatenado, en ese orden). Mismo contenido → mismo ID.

## 2. Estructura de `data/snapshots/<snapshotId>/`

```
CURRENT (en data/snapshots/)  # id del snapshot recomendado (último build no-fixture; si solo hay fixtures, el último)
manifest.json              # inventario, SHA-256, procedencia, versión de clasificador
SHA256SUMS                 # sha256sum -c compatible (incluye manifest.json)
articles.jsonl             # una noticia válida por línea
indicators.jsonl           # 540 filas (6 países x 6 indicadores x 15 años) con nulos conservados
predictions.jsonl          # una predicción de categoría por artículo (incl. indeterminado)
clusters.jsonl             # grupos de duplicados / evento
invalid.jsonl              # registros descartados (con motivo) -- T01
quality_report.json        # reporte de calidad de la carga
events.geojson             # (opcional) USGS, PDF §6C
noticias.csv  indicadores.csv  fuentes.json   # contrato de archivos del PDF §7
DATA_DICTIONARY.md  TERMS_OF_USE.md
```

Los datos crudos (`raw/`) viven en `data/raw/<snapshotId>/` y **no** se redistribuyen (derechos de TVN/GDELT: solo metadatos + receta).

## 3. Categorías (PDF §3 etapa 2)

`category ∈ { "economia", "logistica_canal", "turismo", "servicios_publicos", "eventos_naturales", "regulacion", "indeterminado" }`

Etiquetas legibles (es): Economía, Logística/Canal, Turismo, Servicios públicos, Eventos naturales, Regulación, Indeterminado.

## 4. `articles.jsonl`

| Campo | Tipo | Descripción |
|---|---|---|
| `articleId` | string | `"art_" + sha256(canonicalUrl)[:16]`. Determinista. Fixtures: `"fx_" + …`. |
| `title` | string | Titular tal cual (espacios normalizados). No vacío. |
| `url` | string | URL original http(s). |
| `canonicalUrl` | string | URL canónica: esquema+host en minúsculas, sin `www.`, sin fragmento, sin parámetros de tracking (`utm_*`, `fbclid`, `gclid`…), sin `/` final, `http→https`. Clave de deduplicación. |
| `domain` | string | Host sin `www.`. |
| `outlet` | string | Nombre del medio (`"TVN Panamá"`, o dominio si no se conoce). |
| `isTvn` | bool | `true` si `domain` es `tvn-2.com`. |
| `language` | string\|null | ISO 639-1 (`"es"`, `"en"`…); `null` si desconocido. |
| `sourceCountry` | string\|null | País del medio según GDELT (texto) si existe. |
| `publishedAt` | string\|null | Publicación original UTC. RSS: `pubDate`. GDELT **no** da publicación: queda `null` salvo que se infiera de un patrón fecha en la URL (`publishedAtBasis = "url_pattern"`). |
| `publishedAtBasis` | `"rss_pubdate"\|"news_sitemap_publication"\|"url_pattern"\|"unknown"` | Cómo se obtuvo `publishedAt`. Sitemap usa `news:publication_date`, no `lastmod`. |
| `detectedAt` | string\|null | Detección: GDELT `seendate`. RSS: `null` (se usa `extractedAt`). **No es** fecha de publicación (PDF §7). |
| `extractedAt` | string | Momento de extracción UTC. |
| `effectiveDate` | string | Fecha de **observación** usada para ventanas y orden: `detectedAt ?? publishedAt ?? extractedAt`. Para urgencia use `publishedAt` si no es null; si es null, tratar como «fecha de publicación desconocida». |
| `topicHint` | string\|null | `tema` del PDF: etiqueta de la consulta que lo recuperó (p. ej. `"logistica"`); **no** es la clasificación (esa está en `predictions`). |
| `origin` | object | `{ "source": "tvn_rss"\|"gdelt_doc"\|"fixture", "query": string\|null, "endpoint": string }` |
| `textScope` | `"headline_metadata"` | Siempre; la salida editorial debe decir «basado únicamente en titular/metadatos». No se redistribuyen descripciones/cuerpos. |
| `provenance` | object | `{ "key": string, "kind": "agency"\|"outlet"\|"unknown", "agency": string\|null, "known": bool }`. `key` agrupa orígenes: una agencia replicada = una procedencia (`"agency:efe"`, `"outlet:tvn-2.com"`, `"unknown:<domain>"`). Detectada por firmas en titular/URL (EFE, AFP, AP, Reuters, Europa Press, ANSA, Xinhua, Prensa Latina, DPA, Bloomberg). |
| `dataOrigin` | `"real"\|"fixture"` | Ver §1. |
| `provisional` | bool | Hereda de `manifest.provisional`. |
| `sourceRank` | int | Orden estable de aparición en la extracción (diagnóstico). |
| `urlVariantsSeen` | int | *(añadido 1.0.1, aditivo)* Cuántas veces apareció la misma `canonicalUrl` (variantes con tracking, otras consultas) antes de colapsar. |

## 5. `indicators.jsonl` (Banco Mundial; PDF §6B/§7)

Cuadrícula completa 6 países × 6 indicadores × 15 años (2010–2024) = **540 filas**. (El PDF §6B y el PLAN dicen «1.350 combinaciones»; la aritmética del PDF es inconsistente: 6×6×15 = 540. Se conservan todas las combinaciones reales y sus faltantes; ver DECISIONES.) las faltantes con `value = null`, `status = "missing"`.

| Campo | Tipo | Descripción |
|---|---|---|
| `indicatorRowId` | string | `"ind_<ISO3>_<indicatorId>_<year>"`, p. ej. `ind_PAN_NY.GDP.MKTP.KD.ZG_2023`. |
| `countryIso3` | string | `PAN CRI COL DOM MEX GTM`. |
| `countryName` | string | |
| `indicatorId` | string | `NY.GDP.MKTP.KD.ZG`, `FP.CPI.TOTL.ZG`, `SL.UEM.TOTL.ZS`, `SP.POP.TOTL`, `IT.NET.USER.ZS`, `NE.EXP.GNFS.ZS`. |
| `indicatorName` | string | Nombre original (inglés, WB). |
| `year` | int | 2010–2024. Es el **año de referencia** del dato anual, no una medición «de hoy» (T04). |
| `value` | number\|null | Valor original sin redondear ni rellenar. |
| `unit` | string | Unidad legible: `"% anual"`, `"% de la fuerza laboral"`, `"personas"`, `"% de la población"`, `"% del PIB"`. |
| `status` | `"ok"\|"missing"` | |
| `sourceUrl` | string | URL exacta de la consulta (una por indicador × país). |
| `sourceLastUpdated` | string\|null | `lastupdated` de la respuesta WB (fecha). |
| `extractedAt` | string | UTC. |
| `license` | string | `"CC BY 4.0 (salvo excepciones en metadatos del indicador)"`. |
| `dataOrigin` | `"real"\|"fixture"` | Solo el modo `fixture-snapshot` (CI) genera indicadores `fixture` (`indicatorRowId` con prefijo `fx_ind_`). |

## 6. `predictions.jsonl` (una por artículo; Laya o baseline)

| Campo | Tipo | Descripción |
|---|---|---|
| `predictionId` | string | `"pred_" + sha256(articleId + inputHash + modelId)[:16]`. |
| `articleId` | string | FK a `articles.jsonl`. |
| `inputHash` | string | SHA-256 hex del texto de entrada normalizado (hoy: titular, NFC, espacios colapsados, sin minúsculas forzadas). **Hash de entrada de Laya**: permite verificar que la predicción corresponde al texto del snapshot. |
| `task` | `"category"` | |
| `category` | string | Una de §3. `indeterminado` si `probability < threshold` o margen pequeño. |
| `probability` | number | Probabilidad de la categoría ganadora antes de aplicar `indeterminado` (0–1). Sin calibrar (`calibrated=false`) hasta evaluarla. |
| `probabilities` | object | `{ categoria: p }` para las 6 categorías. Baseline: suma ≈ 1 sobre las 6. Laya: además la clave `indeterminado` = probabilidad de la opción «otro»; la suma sobre las 7 claves ≈ 1. |
| `calibrationLogits` | object\|absent | *(1.1.0, opcional)* Logits de categoría posteriores a la temperatura interna de Laya y anteriores al ajuste de Umbral; conserva precisión completa para reproducir temperature scaling. Sus claves son las seis categorías y `otro`. |
| `calibratedProbabilities` | object\|absent | *(1.1.0, opcional)* Distribución de las mismas 7 salidas tras temperature scaling; `probabilities` conserva la distribución cruda para auditoría. |
| `threshold` | number | Umbral aplicado para `indeterminado`. |
| `geoRelevance` | `"panama"\|"regional"\|"none"\|"indeterminate"` | Relevancia geográfica **por contenido del titular** (regla léxica auditable `lexical-content-v2`, no por modelo ni por medio): `panama` si nombra Panamá/lugares/entidades panameñas o «B/.»; `regional` si nombra países de la lista del PDF o Centroamérica/Latinoamérica/Caribe; `none` si nombra solo lugares/actores extranjeros; `panama` también si la fuente es panameña (TVN, `.pa` o `sourceCountry=Panama`) **y** el titular no nombra nada extranjero; si no hay señal, `indeterminate`. Alimenta R de `scoring-v1` (1 / 0,5 / 0 / 0). |
| `geoEvidence` | string[] | Términos que activaron la regla (`contenido:chiriqui`, `extranjero:trump`, `fuente_panameña:sin_señal_extranjera`, …). Vacío si `indeterminate`. |
| `geoMethod` | string | *(1.0.2, aditivo)* `lexical-content-v2`. |
| `geoLayaRaw` | object\|absent | *(1.0.2, aditivo)* Solo con Laya: probabilidades crudas de su pregunta geo `{panama, regional, none}` (diagnóstico; NO se usan para `geoRelevance`). |
| `classifier` | `"laya"\|"baseline"` | **Si es `baseline`, no es Laya**; también en `manifest.classifier`. |
| `modelId` | string | `"convaiinnovations/laya"` o `"baseline-lexical-v1"`. |
| `modelVersion` | string | Revisión/commit HF (o versión del baseline). |
| `predictedAt` | string | UTC. |
| `calibrated` | bool | `true` solo si se aplicó un perfil validado; `false` mientras el perfil esté pendiente. |
| `calibrationProfileId` | string\|absent | *(1.1.0, opcional)* Identificador inmutable del perfil aplicado. |
| `provisional` | bool | |

## 7. `clusters.jsonl` (agrupación de duplicados / evento)

Todo artículo pertenece a exactamente un cluster (los sin duplicados forman clusters de tamaño 1).

| Campo | Tipo | Descripción |
|---|---|---|
| `clusterId` | string | `"evt_" + sha256(sorted(articleIds).join("\|"))[:16]`. |
| `memberArticleIds` | string[] | Ordenados por `effectiveDate` asc, luego `articleId`. |
| `representativeArticleId` | string | Miembro más antiguo con fecha de publicación conocida; si no, el de menor `articleId`. |
| `size` | int | |
| `category` | string | Categoría del cluster (voto ponderado por probabilidad de los miembros). |
| `provenanceKeys` | string[] | Claves únicas de procedencia (`articles[].provenance.key`). |
| `independentProvenanceCount` | int | Procedencias independientes: miembros con la misma `provenance.key` cuentan 1 (agencia replicada, T02/CU-03), y titulares casi idénticos (token_sort_ratio ≥ 95) en medios distintos se consideran réplica de una misma fuente y cuentan 1. Nunca supera el nº de claves distintas. Repetición ≠ corroboración. |
| `outletCount` | int | Medios distintos (informativo; NO es corroboración). |
| `links` | object[] | Aristas que unieron el cluster: `{a, b, method ∈ {"canonical_url","title_exact","title_fuzzy","bm25_laya"}, score}`. |
| `ambiguous` | bool | `true` si algún miembro tiene candidatos en zona gris (BM25/RapidFuzz) que NO se unieron (no hay desempate o este dijo «distintos»). |
| `ambiguousCandidateIds` | string[] | *(1.0.1)* articleIds candidatos (fuera del cluster) que podrían ser el mismo evento; revisión humana. |
| `firstPublishedAt` / `lastPublishedAt` | string\|null | Min/máx `publishedAt` de miembros conocidos. |
| `originalPublishedAt` | string\|null | Fecha original del evento (la más antigua conocida). Mostrar **esta** en T03. |
| `isRecirculation` | bool | Noticia antigua recirculada (T03). |
| `recirculationReason` | string\|null | p. ej. `"detectedAt 2026-09-30 vs publishedAt 2026-03-12 (200 d)"`. |
| `hasContradictionCandidate` | bool | Heurística de **candidato** (T05), no afirmación: (a) cifras distintas dentro del cluster, o (b) otro cluster del mismo tema (≥4 tokens comunes sin cifras) con cifras distintas (años excluidos). Requiere revisión humana. |
| `contradictionCandidateIds` | string[] | *(1.0.1)* articleIds de OTROS clusters candidatos a contradecir (caso b). |
| `provisional` | bool | |

## 8. `invalid.jsonl` (T01)

`{ "rejectId", "source": "tvn_rss"|"gdelt_doc"|"world_bank"|"fixture", "reasons": string[], "reasonCodes": string[], "raw": object, "rejectedAt" }`. `reasonCodes ∈ { "missing_title","missing_url","invalid_url","invalid_date","null_date","date_out_of_window","duplicate_url","empty_row","bad_id","missing_field" }`. Los inválidos no entran en `articles.jsonl` y no bloquean la carga. `raw` está truncado a 2.000 caracteres por campo.

## 9. `quality_report.json`

```json
{
  "schemaVersion": "1.0.0",
  "snapshotId": "...", "generatedAt": "...Z",
  "news": { "fetched": int, "valid": int, "invalid": int, "invalidByCode": {code: int},
            "uniqueCanonicalUrls": int, "tvnValid": int, "gdeltValid": int,
            "nullPublishedAt": int, "targetMet": bool, "minimumMet": bool,
            "tvnMinimumMet": bool, "coverageWindow": {"start","end","days"}, "widenedTo90Days": bool },
  "indicators": { "expectedCombinations": 540, "rows": int, "withValue": int, "missing": int,
                   "missingByIndicator": {id: int}, "missingByCountry": {iso3: int} },
  "classification": { "classifier": "laya|baseline", "indeterminate": int, "byCategory": {c: int} },
  "clusters": { "count": int, "duplicatesMerged": int, "ambiguous": int, "recirculation": int },
  "checks": [ {"id", "ok": bool, "detail"} ],
  "warnings": [string]
}
```

## 10. `manifest.json`

```json
{
  "schemaVersion": "1.0.0",
  "snapshotId": "20261007-ab12cd34",
  "version": "1.0.0",              // versión del paquete (PDF §7 "versión")
  "provisional": true,             // true mientras no exista paquete oficial congelado de la organización (PDF §6) o haya fixtures/faltantes
  "provisionalReasons": ["no_official_frozen_package"],   // lista de motivos; vacía => provisional=false
  "containsFixtures": false,
  "cutoffUtc": "2026-10-07T...Z",  // fecha_corte_UTC; fechas contra este corte (scoring-v1)
  "createdAt": "...Z",
  "pipeline": { "name": "umbral_pipeline", "version": "0.1.0", "python": "3.12.x" },
  "window": { "startUtc": "...", "endUtc": "...", "days": 30, "widenedTo90": false,
              "note": "Decisión del usuario (cierra D-01): se ignora el intervalo [2024-01-01, 2025-10-01) del PDF §7; ventana = 30 días previos a la extracción (ampliable a 90); corte = fecha de extracción." },
  "queries": [ {"source", "endpoint", "query", "from", "to", "returned"} ],
  "files": { "articles.jsonl": {"sha256": "...", "bytes": int, "records": int}, "...": {} },
  "counts": { "articlesValid": int, "articlesInvalid": int, "tvn": int, "gdelt": int,
              "indicatorRows": 540, "indicatorValues": int, "clusters": int, "predictions": int },
  "classifier": { "classifier": "laya|baseline", "modelId": "...", "modelVersion": "...",
                  "calibrated": false, "calibrationProfileId": null, "calibrationProfileSha256": null,
                  "runAt": "...Z", "device": "cpu", "predictionsInputSha256": "...", "articlesSha256": "..." },
  "sources": [ {"id","name","url","extractedAt","coverage","fields","license","terms","transformations":[...]} ],
  "licenseNotes": "...",
  "transformations": ["canonicalize_url","dedupe_by_canonical_url","normalize_dates_utc","classify","cluster", "..."],
  "snapshotHashInputs": "sha256(articles)+sha256(indicators)+sha256(predictions)+sha256(clusters)"
}
```

- `files[*].sha256` = SHA-256 hex del archivo en disco tal cual (`sha256sum`).
- **`classifier.predictionsInputSha256`** = SHA-256 de las líneas `"{articleId}:{inputHash}\n"` ordenadas por `articleId`. El backend puede recalcularlo desde `articles.jsonl`+`predictions.jsonl` para comprobar que las predicciones publicadas corresponden al snapshot servido.
- `classifier.articlesSha256` = `files["articles.jsonl"].sha256`.
- `manifest.classifier.calibrationProfileSha256` = SHA-256 del perfil aplicado (`null` si `calibrated=false`); `calibrationProfileId` identifica ese mismo archivo.
- Si `classifier.classifier == "baseline"`, la UI debe indicar «clasificador léxico (baseline), no Laya».

## 11. Verificación

```
uv run --project pipeline python -m umbral_pipeline verify data/snapshots/<id>
```
Recalcula SHA-256 de cada archivo, `snapshotId`, `predictionsInputSha256` y comprueba FK (predicciones y clusters → artículos) y 540 filas de indicadores. Salida 0 = correcto.

## 12. Cosas que NO prometen estos datos

Sin cuerpos de artículos; sin fecha de publicación para la mayoría de GDELT (solo `detectedAt`); sin etiquetas de verdad/falsedad; `contradiction` solo candidatos. Indicadores del Banco Mundial son anuales históricos con su `year`; el último año disponible puede tener más faltantes.

