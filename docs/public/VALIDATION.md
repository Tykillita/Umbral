# Validación

Este documento dice **qué se ejecutó, cuándo, con qué resultado y qué no se ha comprobado**. No contiene métricas inventadas: lo que no se ejecutó figura como pendiente. Las pruebas automáticas no sustituyen el juicio editorial humano.

## 1. Reproducción de la CI sobre una copia limpia

- **Fecha:** 2026-10-07, hasta las 19:19 (hora de Panamá). Windows 11, Python 3.12.14 (vía `uv`), Node 24 (dependencia de desarrollo de `apps/web`).
- **Qué se probó:** el árbol exacto que se versionaría, exportado con `git archive` desde el índice a una carpeta nueva y con un `.git` propio, sin `node_modules`, entornos virtuales, builds ni archivos ignorados. Hash del árbol: `d7454b83b7b6254010ced9d72c405fce997f883b` (367 archivos). Este documento se añadió después de esa corrida.
- **Instalación:** con locks congelados (`uv sync --frozen`, `pnpm install --frozen-lockfile`).

| Paso | Comando | Resultado |
|---|---|---|
| Higiene | `uv run --no-project python scripts/check_repo.py --strict` | Aprobado |
| Regla «nada nativo» | `uv run --no-project python scripts/check_no_native_ui.py` | Aprobado |
| API: lint y tipos | `ruff check .` · `mypy src` (24 archivos) | Aprobado |
| API: pruebas | `pytest` (con extra `firebase`) | **269 aprobadas** |
| API: contrato | `python scripts/export_openapi.py --check` | `openapi.json` al día |
| Pipeline | `ruff check .` · `pytest` (sin red ni PyTorch) | Aprobado · **51 aprobadas**, 1 excluida (inferencia Laya con red) |
| Web: tipos | `astro check` (51 archivos) | 0 errores, 0 avisos |
| Web: unitarias | `vitest run` | **68 aprobadas** (10 archivos) |
| Web: compilación | `astro build` en modo local, público y online (API alojada de ejemplo) | 2 páginas cada una |
| Integración y E2E | `pytest tests` con `UMBRAL_TESTS_STRICT=1` y Playwright/Chromium | **200 aprobadas, 0 fallidas, 1 omitida** |

La omitida comprueba que las guías privadas para agentes documentan la regla de interfaz; solo se ejecuta cuando esos archivos existen en el equipo local.

**Defectos que esta reproducción encontró y se corrigieron antes de publicar:** el tipo de salud del frontend no incluía el nuevo campo `deployCommit`; una prueba exigía archivos privados que no se publican; una prueba del verificador de publicación requería un checkout con `.git`; y las pruebas del pipeline fallaban en un equipo cuya carpeta temporal del sistema no era escribible (se resolvió usando una carpeta temporal propia del proyecto).

## 2. Comprobaciones de publicación

`scripts/check_public_files.py` examina los archivos versionados (también los añadidos con `git add -f`) y falla si encuentra instrucciones privadas, coordinación interna, Markdown fuera de la lista publicable, rutas personales, créditos de herramientas de IA, enlaces rotos o mensajes de commit con coautoría de una herramienta de IA. Sus pruebas (`tests/integration/test_publicacion.py`) cubren cada regla, incluido el caso de un documento privado añadido a la fuerza. El verificador de despliegue (`scripts/wait_for_deploy.py`) se prueba contra un servidor local simulado: espera al arranque en frío, rechaza SHA antiguo, modo no público, fixtures, clasificador distinto de Laya, integridad no verificada y CORS ajeno.

Los informes de desarrollo de `eval/` se sustituyeron por copias en las que la ruta de la máquina local figura como `<repo>`; por eso sus hashes de archivo difieren de los de los originales locales. El contenido de las mediciones no cambió.

## 3. Datos y evaluación técnica

| Qué | Resultado | Evidencia |
|---|---|---|
| Snapshot vigente `20261007-cfa338b6` | 991 noticias (122 TVN + 869 GDELT), 540 indicadores, 910 grupos; cero fixtures; **provisional** | `data/snapshots/20261007-cfa338b6/manifest.json` (SHA-256 de cada archivo) |
| Inferencia Laya sin red | Inferencia real sobre el snapshot con DNS y sockets externos bloqueados; 0 intentos externos | `eval/results/laya-offline-20261007-cfa338b6.json` |
| Benchmark de desarrollo (40 consultas escritas por el equipo) | 0 errores HTTP; abstención correcta 14/14; abstención incorrecta 0/20; adversariales 7/7; respuesta con cita 20/20; latencia mediana 0,056 s (caliente, local) | `eval/results/benchmark-dev-20261007-cfa338b6.json` |
| Extensión del benchmark de desarrollo (48 consultas escritas por el equipo: redacciones naturales, cadenas de seguimiento, entidades no vinculables e inyecciones parafraseadas, en otros idiomas, ofuscadas o con homoglifos) | **Antes** de las correcciones de la fase 6: comprobaciones estructurales 20/29 y aviso de instrucción 5/11. **Después**: 29/29 y 11/11; abstención correcta 18/18, incorrecta 0/25, adversariales 11/11, 0 errores HTTP. Sobre los 991 titulares reales, el detector de instrucciones pasó de marcar 4 (el verbo «dan» se confundía con el jailbreak «DAN») a marcar 0 | `eval/results/benchmark-dev-ext-20261007-cfa338b6-before-fixes.json` y `eval/results/benchmark-dev-ext-20261007-cfa338b6.json` |
| Redacción opcional con IA (Gemini real) | Redacción con IA medida con **Gemini real** (`gemini-3.1-flash-lite`, Free Tier; 10 consultas de desarrollo, 11 de las 20 llamadas presupuestadas). Aceptadas por la validación por código: **10/10** (IC 95 % de Wilson 72–100 %); al primer intento 9/10 (60–98 %); rescatada por el único reintento 1/10; ningún respaldo por cuota ni servicio; 0/10 con cifras ausentes de la respuesta por reglas (comprobación independiente). Latencia mediana 1,5 s (máx. 5,7 s); 843 tokens de media. **Límites:** n pequeño, un modelo y un día; la validación prueba estructura (ids, campos, pasajes literales, cifras), no fidelidad. En una lectura de los 10 textos hecha por el agente (no es juicio humano) **2 de 10 pasaron la validación pero perdieron información**: la agenda (`ext_33`) omite puntajes y estado de evidencia y presenta los titulares como hechos sin atribuirlos al medio, y «¿Qué falta verificar del primero?» (`ext_34`) repitió el titular en lugar de la lista de verificaciones. El sustento humano sigue pendiente. **Tras reforzar las reglas** (el código exige ahora atribuir cada titular a su medio, conservar el puntaje de cada tema de la agenda y citar los pendientes en las verificaciones; segunda medición con las mismas 10 consultas y 11 llamadas): aceptadas **8/10** (IC 95 % 49–94 %), 7/10 al primer intento, 1/10 tras el reintento (la lista de verificaciones), validación 8/8 entre las que el modelo respondió (68–100 %), 0/8 con cifras nuevas. Las otras 2/10 conservaron la respuesta por reglas por un `ReadTimeout` de 30 s de Gemini (latencia mediana 17 s ese día frente a 1,5 s en la primera medición; tokens medios 1 241 frente a 843). En la lectura del agente, la agenda y las verificaciones ya conservan puntajes, atribución y tipo de respuesta. Las reglas se escribieron viendo esos mismos casos: es una medición en muestra | `eval/results/compose-gemini-20261008-cfa338b6.json` (antes) y `…-v2.json` (después) (`eval/run_compose_eval.py`) |
| Cuota global de Gemini (emulador de Firestore) | 40 reservas concurrentes en una instancia: 20 aceptadas y 20 rechazadas; el contador siguió agotado con un cliente y un proceso nuevos | `apps/api/diagnostics/public-counter-local.json` |

Límites de esas cifras: el benchmark de desarrollo son **pruebas exploratorias, no el benchmark final ni etiquetas humanas**; la precisión@5 de recuperación (0,2) usa un solo identificador relevante por consulta y **no mide la utilidad editorial de la agenda**; la latencia no incluye Render ni Gemini. Las 48 consultas de la extensión también son sondas estructurales escritas por un agente, sin etiquetas humanas, y **las correcciones se hicieron viendo esos mismos casos**: el «después» es una medición en muestra, no una estimación de generalización (eso lo dirá el benchmark reservado, que no se ha leído ni ejecutado). La redacción opcional con IA tiene su propia medición con Gemini real (fila anterior); el sustento humano de lo redactado sigue pendiente. La cuota se probó en el emulador con una sola instancia de API; un ensayo con varios escritores simultáneos tuvo contención y cayó de forma segura a plantilla. No acredita el Firestore de producción.

## 4. Aplicación de Windows

Compilada y probada en el equipo de desarrollo el 2026-10-07:

- Prueba humo del ejecutable empaquetado, con corte reducido (2 titulares reales y 540 indicadores) y reclasificación Laya real en un proceso aparte: **12 de 12 comprobaciones**, repetida en varias corridas, sin errores de página ni peticiones externas.
- Prueba humo con el snapshot completo de 991 noticias: **7 de 7 comprobaciones**, incluido el cierre ordenado y la terminación del backend local.
- Instalador NSIS sin firma, 822.606.812 bytes, SHA-256 `74ea5c55f643742388a4e414c3b4d17608b0ea13f688b23c418fcb7de5b750c3`; ejecutable sin empaquetar `4b3d4a19d8aa0f401fa0befcd392100904a0a4c01740131fbe4ecbcf88cc31da`.
- Pruebas propias del escritorio: 2 de Node y 7 de Python aprobadas.

**Selector de modelos y actualizador, 2026-10-08 (árbol de trabajo local):**

- `node --test tests/*.test.cjs` en `apps/desktop`: **8/8**; `node node_modules/vitest/vitest.mjs run` en `apps/web`: **99/99**; pruebas de API para compose y sesiones Claude con `uv run --extra firebase pytest`: aprobadas.
- `python scripts/check_no_native_ui.py`: aprobado; integración y E2E `UMBRAL_TESTS_STRICT=1 uv run pytest -q -p no:cacheprovider integration/test_regla_sin_controles_nativos.py e2e/test_sin_controles_nativos.py`: **30 aprobadas**.
- `astro check`: **64 archivos, 0 errores, 0 avisos**; `astro build`: **2 páginas**. Se ejecutaron desde una copia temporal con dependencias instaladas por lock, para conservar el servidor web activo.
- Instalador NSIS de prueba v0.1.0, creado con `electron-builder --win nsis --x64 --publish never`: **823.738.263 bytes**, SHA-256 `235070f5730babaf82d0d973ef0eec089f0a4208f2a9f1fec7090bea1fcc0244`. Se generaron `latest.yml` y `.blockmap`; el modo de publicación fue `never`.
- `apps/desktop/smoke_electron.py` sobre el paquete desempaquetado de esa misma compilación: **12/12 comprobaciones**, cero errores de página y cero solicitudes externas; SHA-256 del ejecutable probado `d36a5980cc38522a3487ab0e9a80bd004f7b13e9e872731d5d9669413e538a60`.
- No había perfiles ChatGPT activos ni sesión OAuth de Claude en este equipo al comprobarlo; las inferencias con cuentas reales quedan pendientes.

**Actualización real con GitHub Releases, 2026-10-08 (Windows; v0.1.0 → v0.1.1):**

- La app v0.1.0 detectó la release nueva y descargó el instalador oficial de [v0.1.1](https://github.com/Tykillita/Umbral/releases/tag/v0.1.1). El instalador Windows x64 fue de **823.288.574 bytes** y su SHA-256 fue `0ddd9d23b37128ddf4cfb965ea88be746b7ea34f306cec4bcdfb8d36853146c6`, coincidente con el digest del asset de GitHub. La release anterior usada como origen fue [v0.1.0](https://github.com/Tykillita/Umbral/releases/tag/v0.1.0).
- El actualizador cerró la versión anterior, ejecutó NSIS y la nueva app se abrió después de que terminara la instalación. La primera apertura se inició mientras NSIS todavía desplegaba archivos y mostró un error temporal del motor; al cerrar esa instancia y abrir de nuevo tras finalizar NSIS, el motor local y la interfaz cargaron correctamente. El ejecutable instalado informó `ProductVersion 0.1.1.0` y `FileVersion 0.1.1`.
- Comprobación local de continuidad: los 316 archivos registrados antes de reinstalar v0.1.0 seguían presentes tras actualizar; los archivos del snapshot anterior conservaron sus hashes. Los cambios se limitaron a la base SQLite/configuración y datos de caché que la app actualiza al abrir. La base SQLite activa y la copia de seguridad creada por el motor conservaron el mismo contenido lógico; no se publican datos ni rutas del perfil.
- El workflow de release [37852126466](https://github.com/Tykillita/Umbral/actions/runs/37852126466) construyó y publicó el instalador y `latest.yml`, pero terminó con error al adjuntar el checksum. Se verificó el instalador contra el digest de GitHub y se adjuntó su archivo `.sha256` a mano. El fallo del paso de carga se corrigió en el workflow por el PR #11; la carga automática del checksum en una ejecución posterior del workflow sigue pendiente.

## 5. CI remota y despliegue alojado

- **CI remota (GitHub Actions), 2026-10-08:** el PR #1 y la integración en `main` pasaron las 5 comprobaciones (higiene, API, pipeline, web, integración y E2E). En la primera ejecución del PR falló una prueba de zonas táctiles que depende del tiempo de la animación de pulsación (43 px en vez de 44 px en el ejecutor Linux); se corrigió esperando a que terminen las animaciones antes de medir (PR #2).
- **Despliegue (workflow «Despliegue», 2026-10-08):**
  - API en Render Free (`https://umbral-m330.onrender.com`): commit `67c9846ba4f733651520ed93184a61ea562e80e9`, `status: ok`, modo público sin persistencia, snapshot `20261007-cfa338b6` (991 noticias, integridad verificada, sin fixtures), clasificador Laya.
  - Web en Firebase Hosting (`https://site-umbral.web.app`), publicada solo después de verificar la API.
  - Prueba online `scripts/verify_hosted.py`: **12 comprobaciones aprobadas** (portada, aplicación, descubrimiento de la API, descriptor de datos, CORS del origen de Hosting, snapshot íntegro, agenda, ficha con evidencia, consulta en español, plantilla con citas y escritura privada rechazada con HTTP 403).
  - La primera ejecución del workflow falló en la autenticación de Firebase Hosting por una credencial inválida; Hosting no se modificó. Se sustituyó la credencial y la segunda ejecución pasó.

Esta prueba **no llama a Gemini real** y no acredita revisión humana.

**Comprobación alojada de solo lectura (2026-10-09, 09:42 UTC):**

- `Invoke-RestMethod -Uri 'https://site-umbral.web.app/data/current.json'`: feed `20261007-cfa338b6`, snapshot provisional; `publishedAt` `2026-10-09T07:01:49.51653Z`, hash del manifest `dbba62f3d01d962d09018f7a00b82e6fd068aa7b705145898a9b2c739a74b050`.
- `Invoke-RestMethod -Uri 'https://umbral-m330.onrender.com/api/v1/health'`: `status: ok`, modo `public`, persistencia `none`, clasificador Laya, snapshot `20261007-cfa338b6`, commit alojado `5dcf938e4cd9062cf1269f381ac9a0f248c75801`.
- `gh run list --repo Tykillita/Umbral --workflow daily-data.yml --limit 10 --json createdAt,status,conclusion,headSha,displayTitle,event`: la última ejecución programada devuelta fue omitida (`skipped`) el `2026-10-08T17:52:19Z`, con SHA `85be6577ba919f0b4eed5a9c0ff2e4eea6df7cb8`.

El feed y la API siguen en el snapshot base provisional. Que el descriptor se haya publicado de nuevo con el mismo ID no demuestra que se haya completado un ciclo nuevo de ingesta; la continuidad diaria y dos ciclos reales siguen pendientes.

## 6. Pendiente (no ejecutado)

- Generación real con Gemini sostenida, el contador de cuota de Firestore de producción y el arranque en frío medido en Render.
- Que Render entregue `CF-Connecting-IP` y el límite por visitante la use (las respuestas pasan por Cloudflare, pero la cabecera hacia el origen no se ha comprobado); si falta, se conserva el límite compartido por socket.
- **Dos ciclos reales** del workflow diario, rechazo de un snapshot corrupto en producción y continuidad de casos archivados.
- **Instalación en un Windows limpio** y uso sin internet.
- Una ejecución completa de `release-desktop.yml` desde un tag estable con carga automática del checksum. El workflow de v0.1.1 publicó el instalador y `latest.yml`, pero falló en ese último paso; el checksum de esa release se adjuntó manualmente. La actualización real v0.1.0 → v0.1.1 mediante GitHub Releases ya se ejecutó y se documenta arriba.
- Inferencia real con cuentas conectadas de ChatGPT o Claude; no había sesión activa disponible al verificarlas el 2026-10-08.
- **Revisión humana:** clasificación y geografía, agrupación de duplicados, sustento de afirmaciones, Precision@5 editorial de la agenda y el benchmark reservado de 20 consultas, que vive fuera de este repositorio y no se ha leído.
- Paquete oficial congelado de noticias (el snapshot sigue siendo provisional).
