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
| Cuota global de Gemini (emulador de Firestore) | 40 reservas concurrentes en una instancia: 20 aceptadas y 20 rechazadas; el contador siguió agotado con un cliente y un proceso nuevos | `apps/api/diagnostics/public-counter-local.json` |

Límites de esas cifras: el benchmark de desarrollo son **pruebas exploratorias, no el benchmark final ni etiquetas humanas**; la precisión@5 de recuperación (0,2) usa un solo identificador relevante por consulta y **no mide la utilidad editorial de la agenda**; la latencia no incluye Render ni Gemini. La cuota se probó en el emulador con una sola instancia de API; un ensayo con varios escritores simultáneos tuvo contención y cayó de forma segura a plantilla. No acredita el Firestore de producción.

## 4. Aplicación de Windows

Compilada y probada en el equipo de desarrollo el 2026-10-07:

- Prueba humo del ejecutable empaquetado, con corte reducido (2 titulares reales y 540 indicadores) y reclasificación Laya real en un proceso aparte: **12 de 12 comprobaciones**, repetida en varias corridas, sin errores de página ni peticiones externas.
- Prueba humo con el snapshot completo de 991 noticias: **7 de 7 comprobaciones**, incluido el cierre ordenado y la terminación del backend local.
- Instalador NSIS sin firma, 822.606.812 bytes, SHA-256 `74ea5c55f643742388a4e414c3b4d17608b0ea13f688b23c418fcb7de5b750c3`; ejecutable sin empaquetar `4b3d4a19d8aa0f401fa0befcd392100904a0a4c01740131fbe4ecbcf88cc31da`.
- Pruebas propias del escritorio: 2 de Node y 7 de Python aprobadas.

## 5. CI remota y despliegue alojado

- **CI remota (GitHub Actions), 2026-10-08:** el PR #1 y la integración en `main` pasaron las 5 comprobaciones (higiene, API, pipeline, web, integración y E2E). En la primera ejecución del PR falló una prueba de zonas táctiles que depende del tiempo de la animación de pulsación (43 px en vez de 44 px en el ejecutor Linux); se corrigió esperando a que terminen las animaciones antes de medir (PR #2).
- **Despliegue (workflow «Despliegue», 2026-10-08):**
  - API en Render Free (`https://umbral-m330.onrender.com`): commit `67c9846ba4f733651520ed93184a61ea562e80e9`, `status: ok`, modo público sin persistencia, snapshot `20261007-cfa338b6` (991 noticias, integridad verificada, sin fixtures), clasificador Laya.
  - Web en Firebase Hosting (`https://site-umbral.web.app`), publicada solo después de verificar la API.
  - Prueba online `scripts/verify_hosted.py`: **12 comprobaciones aprobadas** (portada, aplicación, descubrimiento de la API, descriptor de datos, CORS del origen de Hosting, snapshot íntegro, agenda, ficha con evidencia, consulta en español, plantilla con citas y escritura privada rechazada con HTTP 403).
  - La primera ejecución del workflow falló en la autenticación de Firebase Hosting por una credencial inválida; Hosting no se modificó. Se sustituyó la credencial y la segunda ejecución pasó.

Esta prueba **no llama a Gemini real** y no acredita revisión humana.

## 6. Pendiente (no ejecutado)

- Generación real con Gemini sostenida, el contador de cuota de Firestore de producción y el arranque en frío medido en Render.
- Que Render entregue `CF-Connecting-IP` y el límite por visitante la use (las respuestas pasan por Cloudflare, pero la cabecera hacia el origen no se ha comprobado); si falta, se conserva el límite compartido por socket.
- **Dos ciclos reales** del workflow diario, rechazo de un snapshot corrupto en producción y continuidad de casos archivados.
- **Instalación en un Windows limpio**, uso sin internet y actualización del instalador sin pérdida de trabajo.
- **Revisión humana:** clasificación y geografía, agrupación de duplicados, sustento de afirmaciones, Precision@5 editorial de la agenda y el benchmark reservado de 20 consultas, que vive fuera de este repositorio y no se ha leído.
- Paquete oficial congelado de noticias (el snapshot sigue siendo provisional).
