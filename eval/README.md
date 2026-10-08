# Evaluación: estado actual y reproducción

**CURRENT=20261007-cfa338b6**:991 noticias reales (122TVN+869GDELT),910grupos,540indicadores y82USGS. Laya con scope laya-category-v1 y geo lexical-content-v2; cero fixtures; ventana90d. Objetivo200 cumplido. Siete consultas GDELT fallidas y714 publicaciones desconocidas son límites reales conservados. Todos los snapshots anteriores se preservan.

Manifest SHA-256: dbba62f3d01d962d09018f7a00b82e6fd068aa7b705145898a9b2c739a74b050. Provisional por falta de paquete oficial y cobertura parcial; no implica aceptación del jurado.

## Qué está medido

- Dev40 cfa338b6:0HTTP,abstención14/14,adversarial7/7,incorrecta0/20,cita porrespuesta20/20. Son pruebas exploratorias escritas por el agente, no benchmark final ni etiquetas humanas. P@5recuperación parcial0,2 usa unID relevante por consulta (máximo0,2), no utilidad editorial de agenda. Latencia local caliente; no Render/Gemini.
- Layaoffline sobre cfa338b6: inferencia real con DNS/sockets externos bloqueados,0intentos externos modelo. No es macro-F1.
- Claims reales:32/32 tienen IDs/campos existentes; **cobertura factual estructural**, no sustento humano. Juicios0, valoreshumanosnull.
- Clasificación,agrupación,agendaP@5 y sustento: CLIs ejecutados sobre muestras actuales vacías reportanpending/null; las métricas reales necesitan revisor.
- Verificador eval/verify_eval_tools.py ejecuta siete controles analíticos **sintéticos**: comparaciónF1 baseline/Laya controlados,Brier/ECE,PRpares,agendaP@5,claims y rechazohashalterado. Receipt en eval/verification/20261007T150254Z/receipt.json; nunca se agregan como desempeño humano.

Baseline real preparado en 20261007-55d70099,991artículos con **mismo SHA-256 de artículos** que Laya actual;924clusters. Noactivado. Se puede usar la misma revisión humana para comparar; no se inventaron etiquetas ni resultados de calidad.

## Pendientes humanos indispensables

1. Rellenar los CSV de cfa338b6 según labels/LEEME.md:120titulares,50pares,32afirmaciones. Ocultar predicciones al juzgar para reducir anclaje. Import conserva autoría/snapshot/hash. No sustituir juicios por predicciones.
2. Juzgar utilidad editorial y completar relevantTopicIds en labels/agenda_review.cfa338b6.jsonl; ranking capturado results/agenda-ranking-cfa338b6.json. El juicio debe ser independiente del puntaje.
3. Evaluador independiente prepara/ejecuta20reservadas fuera del repo/UI/contextoagentes (10sustentadas,4ambiguas,3sinrespuesta,3adversariales para total30/10/10/10). Agente no las leyó/creó/ejecutó.
4. Organización/usuario confirma paquete congelado y aceptación de límites de fuentes.

Muestras/CSV existentes se conservan. Los runners no reemplazan revisión humana; rutas nuevas explícitas para otra muestra. Agregador rechaza synthetic_control/unverified_labels y snapshots diferentes. Brier/ECE son diagnóstico **crudo**, no fitting ni calibración con etiquetas del agente.

## Comandos desde la raíz

```powershell
pipeline/.venv/Scripts/python.exe -m umbral_pipeline verify data/snapshots/20261007-cfa338b6
pipeline/.venv/Scripts/python.exe -m pytest pipeline/tests -q
pipeline/.venv/Scripts/python.exe -m ruff check pipeline eval
pipeline/.venv/Scripts/python.exe eval/verify_eval_tools.py

# Solo después de revisión humana:
pipeline/.venv/Scripts/python.exe eval/make_label_sheets.py import --snapshot data/snapshots/20261007-cfa338b6 --labeler "Nombre del revisor"
pipeline/.venv/Scripts/python.exe eval/run_classification.py --labels eval/labels/cls_labels.20261007-cfa338b6.jsonl --snapshot laya=data/snapshots/20261007-cfa338b6 --snapshot baseline=data/snapshots/20261007-55d70099 --out eval/results/classification-human-cfa338b6.json
pipeline/.venv/Scripts/python.exe eval/run_clustering_eval.py --labels eval/labels/pairs_labels.20261007-cfa338b6.jsonl --snapshot laya=data/snapshots/20261007-cfa338b6 --snapshot baseline=data/snapshots/20261007-55d70099 --out eval/results/clustering-human-cfa338b6.json
pipeline/.venv/Scripts/python.exe eval/run_claims_eval.py --snapshot data/snapshots/20261007-cfa338b6 --labels eval/labels/claims_labels.20261007-cfa338b6.jsonl --out eval/results/claims-human-cfa338b6.json
pipeline/.venv/Scripts/python.exe eval/run_agenda_eval.py --snapshot data/snapshots/20261007-cfa338b6 --ranking eval/results/agenda-ranking-cfa338b6.json --labels eval/labels/agenda_review.cfa338b6.jsonl --out eval/results/agenda-human-cfa338b6.json
pipeline/.venv/Scripts/python.exe eval/aggregate_metrics.py
```

Layaoffline vigente: results/laya-offline-20261007-cfa338b6.json conserva comando,flags,hash y evidencia de bloqueo. No repetir benchmark/modelos sin cambios que justifiquen la verificación.

## Extensión opcional de fuente (no cambia CURRENT)

Se descubrió el sitemap Google News TVN publicado en robots.txt/índice oficial:220titulares con news:publication_date. Ingesta opcional fetch --sources tvn-sitemap, publicada en contrato1.0.3aditivo. Nunca usa lastmod como publicación, ni guarda cuerpos/imágenes. Candidato289(0adf643a) verificado con no-set-current **no activado** porque991 ya cumple objetivo; conserva todos los snapshots. Es preparación para futuras extracciones, no reemplazo del corpus.

## Historia del ajuste de alcance y procedencia

Las secciones siguientes preservan el diagnóstico de los cortes anteriores; donde describen CURRENT antiguo se refieren a esa ejecución histórica. La cabecera anterior y data/snapshots/CURRENT son el estado vigente.
## Control de alcance de Laya (snapshot 20261007-cdba136d, cambio de método)

**Problema (observado en 37263360):** Laya elegía siempre una de las seis categorías del reto; sucesos policiales, humor o farándula salían como `eventos_naturales` con probabilidades altas (p. ej. 0,87 y 0,71) y entraban en la agenda.

**Método (diseño, sin ajuste sobre etiquetas del corpus):** la pregunta de Laya incluye `otro` como opción de primer orden con descripción explícita («sucesos policiales, crímenes, accidentes, deportes, espectáculos, farándula, política internacional, curiosidades…»); si `otro` gana o la ganadora queda bajo el umbral 0,5 la etiqueta es `indeterminado`. Las **probabilidades crudas se conservan** en `predictions.probabilities` (la clave `indeterminado` es la probabilidad de «otro»). Se retiraron de los criterios «seguridad ciudadana», «casos judiciales» y «alertas», que atraían ruido. Código: `pipeline/umbral_pipeline/classify/laya_clf.py` (`CATEGORY_QUESTION_V1`, `SCOPE_METHOD = laya-category-v1`, `decide_category`); el manifest lo registra en `classifier.scopeMethod`.

**Sondeo exploratorio** (`eval/exploratory/probe_scope.py`, resultado completo con probabilidades crudas en `eval/results/scope-probe-20261007.json`): 36 titulares ajenos al alcance y 30 dentro del alcance (5 por categoría), **escritos por el equipo como ejemplos genéricos, no tomados del corpus real**; un solo autor, n pequeño: es exploratorio, no macro-F1 ni etiquetas humanas. Regla fijada de antemano: máxima detección de fuera-de-alcance con retención de dentro-de-alcance ≥ 60 %; empate → la variante más simple (una sola pasada).

| Variante | Fuera de alcance detectado | Dentro de alcance retenido (categoría exacta) |
|---|---|---|
| v0 (original, 37263360) | 28/36 | 25/30 (24/30) |
| v0 + margen 0,2 | 30/36 | 25/30 (24/30) |
| **v1: `otro` explícito (elegida)** | **36/36** | **22/30 (21/30)** |
| v1b: criterios ampliados | 34/36 | 19/30 (19/30) |
| v1 + puerta binaria `scope` (≥0,5 / ≥0,8 / ≥0,95) | 36/36 en los tres umbrales | 15/30 / 20/30 / 22/30 (con ≥0,95 equivale a v1 y añade una pasada) |

Un criterio de margen entre 1.ª y 2.ª probabilidad no habría resuelto el caso original (0,87 frente a 0,03). **Coste reconocido:** v1 deja de reconocer 8/30 titulares dentro de alcance (p. ej. salud/educación, Zona Libre, cruceros, proyecto de ley de la Asamblea) como `indeterminado`.

**Efecto sobre los 122 titulares reales** (`eval/results/classification-change-37263360-to-cdba136d.json`, sin etiquetas humanas): cambian **28/122**. Antes: indeterminado 74, economia 32, eventos_naturales 5, logistica_canal 4, regulacion 3, turismo 2, servicios_publicos 2. Ahora: **indeterminado 99, economia 17, logistica_canal 2, regulacion 2, turismo 1, servicios_publicos 1** y 0 eventos_naturales. Movimientos: economia→indeterminado 17, eventos_naturales→indeterminado 5, logistica_canal→indeterminado 2, turismo→indeterminado 1, servicios_publicos→indeterminado 1, regulacion→economia 1, indeterminado→economia 1. Los dos casos señalados pasan a `indeterminado` (0,48 y 0,90). Entre los 28 hay correcciones claras (deportes, farándula, comunicados de marca, política internacional) y **falsos indeterminados probables** (p. ej. «MOP solicita $43,1 millones…», «El bitcoin supera los 80.000 dólares»; además «Panamá mantiene vigilancia epidemiológica…» ya era indeterminado y sigue siéndolo). Sin etiquetas humanas no se puede cuantificar el acierto: sigue pendiente el etiquetado de `labels/cls_sample.jsonl` para el macro-F1.

**Agenda (backend `GET /topics?limit=8`, API temporal sobre cada snapshot):** top-5 anterior: 2 temas eventos_naturales a 80,8 (taxista, chatarra), liga de fútbol, comisión de presupuesto, apoyo a la democracia. Top-5 nuevo (todos 74,5): liga de fútbol, comisión de presupuesto, apoyo a la democracia, vigilancia epidemiológica (peste neumónica), Trump/anuncios de TV. **El ruido no desaparece:** `scoring-v1` calcula R solo con la relevancia geográfica y no con la categoría, así que un tema `indeterminado` con geo=panamá sigue puntuando; el fútbol sigue en el top 5. Hace falta que el backend use `category == indeterminado` (fuera de alcance) para R o para excluir de la agenda; el pipeline ya entrega la señal.

**Dev benchmark rehecho** sobre cdba136d (`eval/dev/benchmark_dev.jsonl` regenerado, el anterior en `benchmark_dev.20261007-37263360.jsonl`; 6 casos de desarrollo cambian porque `prepare_dev.py` selecciona por categoría): 0 errores HTTP, abstención 14/14, adversariales 7/7, abstención incorrecta 0/20, presencia de cita 20/20, P@5 parcial 0,2. `labels/claims_sample.jsonl` (sin etiquetas) corresponde a temas del snapshot anterior y se conservó sin tocar.

## Candidato con GDELT: 20261007-d60d2630 (adoptado después como base; superado por cfa338b6)

La extracción GDELT de `data/raw/20261007T072855Z` sí obtuvo 874 registros (panama 750, logistica 123, turismo 1; el resto de consultas dio 429) que no se habían usado. Se validaron y se construyó un candidato: **991 noticias válidas (122 TVN + 869 GDELT), objetivo de 200 cumplido**, 910 clusters (24 de tamaño 2, 7 de 3, 14 con ≥2 procedencias independientes), 80 rechazos, 540/540 indicadores, verify OK, `provisionalReasons = [no_official_frozen_package, gdelt_query_failures]`. Laya: indeterminado 801, economia 121, turismo 19, eventos_naturales 15, logistica_canal 15, servicios_publicos 11, regulacion 9. `CURRENT` sigue en cdba136d porque cambiar a 991 titulares afecta fichas, benchmark y pruebas ya validados; decide el coordinador. GDELT no trae fecha de publicación (`publishedAt` null salvo patrón en la URL).


## CURRENT = 20261007-cfa338b6 (991 noticias): calidad GDELT, geo por contenido, independencia

Construcción: `build --raw data/raw/20261007T081434Z --extra-raw data/raw/20261007T080820Z --extra-raw data/raw/20261007T072855Z --classifier laya`. Misma cobertura que d60d2630 (122 TVN + 869 GDELT; 80 rechazos; objetivo 200 cumplido; 540/540 indicadores; `provisionalReasons = no_official_frozen_package, gdelt_query_failures`). Las categorías de Laya son idénticas a d60d2630 (0 cambios; Laya es determinista); cambian `geoRelevance`, `independentProvenanceCount` y los candidatos de contradicción.

### Auditoría de calidad GDELT (869 titulares, vista por fuente, no solo agregada)
- **Idioma:** es 752, en 89, zh 12, de 10, ko 2, sin idioma 4. La consulta pedía `sourcelang:spanish` pero GDELT devuelve otros idiomas; Laya multilingüe los procesa, pero un 13 % no es español.
- **Fuentes:** 333 dominios; 218 aportan un solo titular. Panameños dominantes: critica.com.pa 61, prensa.com 51, panamaamerica.com.pa 50, telemetro.com 43, midiario.com 43, laestrella.com.pa 37. País del medio (GDELT): Panama 312, EE. UU. 100, Argentina 64, México 42, España 42, Colombia 39, Venezuela 33. Agencias firmadas en el titular: Prensa Latina 6, Xinhua 4, EFE 3, Europa Press 1.
- **Fechas:** `detectedAt` va de 2026-09-10 a 2026-10-06, todas dentro de la ventana. GDELT no da publicación: `publishedAt` es null en 714 (82 %) y se infiere de un patrón de fecha en la URL en 155 (`publishedAtBasis=url_pattern`, heurística).
- **Duplicados entre medios:** 152 URLs repetidas colapsadas; 81 titulares agrupados en 910 clusters. Hay redes de réplica del mismo texto en decenas de dominios (p. ej. 20 sitios con «Intensifying El Nino…», 10 diarios alemanes con el mismo titular, 7 diarios australianos), que cuentan **una** procedencia.
- **Ruido temático:** muchos titulares no tienen relación con Panamá pese a la consulta (cotizaciones de valores `dailypolitical`/`tickerreport`/`themarketsdaily`, «Kurs dolara PLN/USD» de money.pl, cruceros de Sídney a la Antártida, fútbol argentino, política de EE. UU./Venezuela). 702 de 869 quedan `indeterminado` y 174 con relevancia geográfica `none`. Hay titulares de una sola palabra o nombre de sitio (16 de ≤19 caracteres: «Cubadebate», «Confabulario»). Una búsqueda de palabras clave de spam/apuestas dio 5 coincidencias, todas falsos positivos.
- **Derechos:** solo se conservan titular, URL, dominio, idioma, país del medio y marcas de tiempo; no hay cuerpos ni extractos. GDELT no transfiere derechos sobre los artículos enlazados y el snapshot no los redistribuye. Fuentes de procedencia dudosa a tener presentes: replicadores sin autoría (bignewsnetwork.com, britainnews.net, newzealandstar.com, haitisun.com, caribbeanherald.com) y sitios de valores automáticos; conviene excluirlos de cualquier material publicado.
- **«Recirculación»:** 48 clusters marcados `isRecirculation`; casi todos son ítems de TVN cuyo `pubDate` del RSS es 33-62 días anterior a la extracción y siguen en el feed. Es una señal de «noticia antigua presente hoy», no prueba de recirculación editorial.

### `geoRelevance` por contenido (antes: pregunta geo de Laya)
**Auditoría:** en d60d2630 y anteriores `geoRelevance` salía de la pregunta `geo` de Laya sobre el titular (umbral 0,5), **no del medio**, y sobreestimaba `panama`: «Trump no reembolsará…» (TVN) 0,70, un resultado de béisbol mexicano, un titular de Diario Libre sobre una feria, «Secretaría de Obras… mdp». De los 190 titulares con categoría dentro de alcance, 35 tenían `panama` sin mencionar Panamá en el titular.

**Regla nueva (fijada antes de medir, auditable, `lexical-content-v2`, `pipeline/umbral_pipeline/classify/geo.py`):**
1. `panama` si el titular nombra Panamá/panameño, un lugar o entidad panameña de una lista acotada (provincias, ciudades, Canal de Panamá, Sinaproc, Idaan, Etesa, Meduca...), «B/.» o la escritura china/coreana/japonesa de Panamá.
2. Si no, `regional` si nombra un país de la lista del PDF (Costa Rica, Colombia, Rep. Dominicana, México, Guatemala) o Centroamérica/Latinoamérica/Caribe (incluye El Salvador, Honduras, Nicaragua, Belice).
3. Si no, `none` si nombra un lugar/actor/gentilicio extranjero de la lista (EE. UU., Trump, China, Rusia, Europa, «español»...).
4. Si no, `panama` si la fuente es panameña (TVN, `.pa` o país del medio = Panama) y no nombró nada extranjero (se asume tema local; es la única regla que mira el medio).
5. Si no, `indeterminate`.

`geoEvidence` lista los términos que activaron la regla; la respuesta cruda de Laya se conserva en `geoLayaRaw` (diagnóstico). Siglas ambiguas (MOP, MEF, CSS, DGI, Minsa de Perú, Mides de Uruguay) no cuentan por sí solas. La lista de gentilicios extranjeros se añadió **después** de ver que «Sánchez presenta ante el Congreso español...» (TVN) subía al top 5 por la regla 4: es una corrección posterior a una observación, no un parámetro ajustado sobre etiquetas.

**Efecto:** sobre los 991 artículos cambia la relevancia en 639; antes `panama` 275 / `regional` 280 / `none` 144 / `indeterminate` 292, ahora `panama` 468 / `none` 193 / `indeterminate` 273 / `regional` 57. Sobre los 910 clusters (por su representante) cambian 583. Entre los 190 titulares con categoría dentro de alcance: `panama` 73 a 105, `regional` 37 a 11, `none` 29 a 32, `indeterminate` 51 a 42. Por fuente: TVN panama 101 / none 19 / regional 2; GDELT panama 367 / indeterminate 273 / none 174 / regional 55 (de los 367 con contenido panameño, 87 están dentro de alcance).

**Agenda** (API temporal sobre el snapshot, `scope=in_scope` por defecto: 183 temas dentro de alcance y 727 fuera). Top 5 en d60d2630: Canal 76,7; Comisión de Presupuesto 74,55; **Trump no reembolsará 74,55**; Mides 74,55; Canasta básica 67,5. Top 5 en cfa338b6: Canal de Panamá aumenta tránsitos y calado (76,7), Comisión de Presupuesto, Reforma eléctrica en primer debate, Caso Pandora y Mides (los cuatro últimos a 74,55); siguen MIDA (74,55), Chapman/sector privado y Canasta básica (67,5). Salieron Trump y el ruido internacional; entran temas locales. **Límites:** el ranking sigue sin juicio editorial independiente (P@5 de agenda pendiente); hay muchos empates a 74,55; las categorías de Laya erradas dentro de alcance siguen posibles («Caso Pandora» como economía, que más bien es un caso judicial); «Veracruz entra en toque de queda» (¿Panamá o México?) pasa por la regla 4.

### Independencia de procedencia y contradicciones
- `independentProvenanceCount` ahora también colapsa titulares **contenidos íntegros** en otro (>=5 palabras; prefijos/sufijos añadidos por el medio): es una cota conservadora basada solo en titulares; no detecta copias con reescritura. Clusters con >=2 procedencias independientes: 14 (regla antigua) a **7** (Liberty Latin America en 2 sitios de valores, Canal de Panamá newsroompanama/freshplaza, Netanyahu hispantv/tercera, selección argentina, Ministerios Públicos de Paraguay, Ecuador-Japón x3, «Chichero» panamaamerica/laestrella). Solo 2 de los 7 son sobre Panamá; la corroboración independiente real en este corpus es escasa.
- Candidatos de contradicción: ahora solo cuando ambas cifras son excluyentes (ninguna contenida en la otra); {33, 49} frente a {33} ya no se marca (falso positivo señalado por `calidad`). Pasan de 12 a 9 candidatos, todos ruido de cifras que varían por fecha (valores bursátiles, cotización de divisas); **no se detectó ninguna contradicción editorial real**.

### Hojas de etiquetado humano (carga razonable)
`eval/make_label_sheets.py make` creó para cfa338b6 (sin sobrescribir; falla si existen): `clasificacion.20261007-cfa338b6.csv` (120 titulares: 38 TVN + 82 GDELT; 40 uniformes dentro de cada fuente + estratos categoría predicha x fuente), `pares.20261007-cfa338b6.csv` (50 pares: 10 con >=2 procedencias, 16 ambiguos no unidos, 16 copias de una procedencia, 8 negativos de control) y `afirmaciones.20261007-cfa338b6.csv` (32 afirmaciones de borradores de plantilla, una por tema). Columnas `id, texto, predicción, juicio_humano, comentario` (vacías) más sus JSONL de máquina. Instrucciones en español en `eval/labels/LEEME.md`; `make_label_sheets.py import` convierte los CSV rellenados a los JSONL que leen `run_classification.py` y `run_clustering_eval.py`. No contienen las 20 consultas reservadas; no se tocaron `cls_sample.jsonl`, `pairs_sample.jsonl` ni `claims_sample.jsonl` del snapshot 37263360. **Todos los juicios están vacíos: macro-F1, precisión/recall de agrupación y sustento siguen pendientes de etiquetas humanas.**

### Benchmark dev rehecho sobre cfa338b6
`eval/dev/benchmark_dev.jsonl` regenerado (el anterior queda en `benchmark_dev.20261007-cdba136d.jsonl`): 0 errores HTTP; abstención correcta 14/14; adversariales 7/7; abstención incorrecta 0/20; presencia de cita 20/20; P@5 parcial 0,2 (máximo posible por diseño); latencia mediana 0,056 s y p95 0,133 s (local, caliente, offline). Son 40 pruebas estructurales escritas por un agente, no etiquetas humanas ni el benchmark final de 60. Resultado en `eval/results/benchmark-dev-20261007-cfa338b6.json`; `latest.json` ya apunta a cfa338b6.

