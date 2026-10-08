# Diccionario de datos del snapshot

Contrato completo y versionado: `docs/contracts/snapshot-schema.md` (schemaVersion 1.1.0). Resumen:

| Archivo | Registros | Clave | Descripción |
|---|---|---|---|
| `articles.jsonl` | 991 | `articleId` | Noticias válidas (titular + metadatos). Sin cuerpos ni descripciones. |
| `indicators.jsonl` | 540 | `indicatorRowId` | Cuadrícula Banco Mundial 6 países × 6 indicadores × 15 años (2010–2024); faltantes con `value=null`. |
| `predictions.jsonl` | 991 | `predictionId` | Categoría (6 + `indeterminado`), probabilidad, relevancia geográfica, modelo, versión, fecha y `inputHash`. |
| `clusters.jsonl` | 912 | `clusterId` | Grupos de duplicados/evento; procedencias independientes; recirculación. |
| `invalid.jsonl` | 0 | `rejectId` | Registros rechazados con códigos de motivo (T01). |
| `quality_report.json` | – | – | Reporte de calidad de la carga. |
| `manifest.json` / `SHA256SUMS` | – | – | Inventario con SHA-256, ventana, consultas, clasificador. |
| `noticias.csv`, `indicadores.csv`, `fuentes.json` | – | – | Vista compatible con el contrato de archivos del PDF §7. |
| `events.geojson` | 82 | `id` | (Opcional) sismos USGS 2024 en la caja regional del PDF §6C. |

## Reglas
- Fechas ISO 8601 en UTC (`Z`). `publishedAt` es publicación; `detectedAt` es la detección de GDELT (`seendate`) y **no** es publicación.
- GDELT no entrega fecha de publicación: `publishedAt` es `null` salvo patrón de fecha en la URL (`publishedAtBasis = url_pattern`).
- Nulos conservados; nunca se rellenan con 0. Unidades originales en `unit`.
- `textScope = headline_metadata`: toda salida debe decir «basado únicamente en titular/metadatos».
- `dataOrigin = fixture` marca datos sintéticos (prefijo `fx_`); jamás se mezclan sin etiqueta.
- La clasificación no es verdad/falsedad. `category` indica tema; `probability` no está calibrada.
