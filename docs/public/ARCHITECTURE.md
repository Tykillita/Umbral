# Arquitectura

Umbral convierte noticias públicas de Panamá e indicadores oficiales en una agenda priorizada, fichas de evidencia y borradores para revisión humana. Este documento describe cómo encajan las piezas; los contratos exactos están en [`docs/contracts/`](../contracts/snapshot-schema.md).

## Visión general

```
Fuentes públicas ─► pipeline (Laya, Python 3.12) ─► snapshot verificado + SHA-256
                                                        │
                    ┌───────────────────────────────────┤
                    ▼                                   ▼
          Firebase Hosting                       Render (FastAPI, plan Free)
          web estática + feed /data              API pública sin estado
                    │                            Firestore: solo la cuota diaria de Gemini
                    ▼
          Navegador (Astro + React) ── IndexedDB: borradores, revisiones, impacto y pesos

          Windows (Electron): API + pipeline + PyTorch CPU + Laya en un solo instalador; SQLite local
```

| Pieza | Carpeta | Tecnología | Responsabilidad |
|---|---|---|---|
| Pipeline | `pipeline/` | Python 3.12, `uv`, Laya (PyTorch CPU) | Ingesta, validación, clasificación, agrupación de duplicados y exportación del snapshot |
| API | `apps/api/` | FastAPI | Agenda, fichas, consultas, borradores y validación; contrato en `apps/api/openapi.json` |
| Web | `apps/web/` | Astro 7 + React 19 + Tailwind 4 | Interfaz en español; trabajo individual en IndexedDB |
| Escritorio | `apps/desktop/` | Electron + PyInstaller + NSIS | La misma interfaz con API y modelo incluidos, para Windows 10/11 x64 |
| Evaluación | `eval/` | Python | Benchmark de desarrollo y herramientas de métricas (sin el benchmark reservado) |
| Pruebas | `tests/` | pytest + Playwright | Integración y extremo a extremo |

## Datos: el snapshot

Un **snapshot** es una carpeta inmutable `data/snapshots/<AAAAMMDD>-<hash>/` con noticias, indicadores, predicciones, grupos, informe de calidad y un `manifest.json` con el SHA-256 de cada archivo. La API solo sirve un snapshot cuya integridad se verifica al arrancar (`UMBRAL_STRICT_INTEGRITY=1`), que no contiene fixtures y cuyas predicciones proceden de Laya. Los datos crudos no se redistribuyen.

- **Tiempo:** UTC en los datos; hora de Panamá solo al mostrarlos.
- **Ventana:** 30 días previos a la extracción, con solape de 48 horas en la actualización diaria.
- **Indicadores:** 540 combinaciones del Banco Mundial (6 países × 6 indicadores × 15 años). Un indicador anual vinculado a un tema aporta contexto, no sube por sí solo el componente de evidencia.
- **Provisional:** mientras no exista el paquete oficial congelado de noticias, el manifest se marca `provisional`.
- **Actualización diaria:** un workflow construye un candidato, lo verifica y publica `data/current.json` (descriptor) más los últimos siete snapshots válidos. La API y la app de escritorio comprueban el descriptor al arrancar y cada 15 minutos, descargan solo si cambió, validan hashes, referencias y ausencia de fixtures, y sustituyen corpus e índices conjuntamente. Si algo falla conservan el último snapshot válido; con un corte de más de 36 horas muestran un aviso.
- **Casos archivados:** cada caso conserva la evidencia y las citas del snapshot con el que se creó; una actualización no las reescribe.

## Clasificación con Laya

Laya (`convaiinnovations/laya`) se ejecuta en CPU, fijada a la revisión `7b928d828b7b0e022f929d9bd2e44165aa270148`. Clasifica cada titular por categoría y alcance geográfico; la relevancia geográfica final se decide por **contenido** (lugares, regla regional, fuente), no por la pregunta del modelo. Las probabilidades no están calibradas y no deben leerse como tales. No hay sustitución automática por un clasificador de referencia: si Laya falla, el candidato se rechaza.

## Ranking y evidencia

`scoring-v1`: `P = 30R + 25I + 20U + 15N + 10E`, con rangos bajo `[0,40)`, medio `[40,70)` y alto `[70,100]`; desempate por urgencia y luego ID.

- **R** relevancia para Panamá · **I** impacto · **U** urgencia · **N** novedad · **E** evidencia.
- **E = 1** exige una fuente primaria confirmada por una persona revisora; el contenido patrocinado se marca y limita `E ≤ 0,33`.
- El **estado de evidencia** (insuficiente, parcial, suficiente para el borrador) es independiente del puntaje. Una agencia replicada cuenta como **una** procedencia independiente.
- Los temas fuera de alcance (categoría indeterminada) quedan fuera de la agenda por defecto.
- Las salidas se basan en titulares y metadatos; una cita válida en su estructura no prueba que la afirmación esté sustentada.

## Borradores

Cada borrador cita fuentes del snapshot y declara su origen: **generado por un modelo**, **recuperado** de una ejecución anterior o **construido con plantilla**. Toda cita se valida contra el snapshot. El texto de una fuente se trata como dato, nunca como instrucción. Aprobar un borrador no lo publica.

- **Gemini** (nivel gratuito, sin facturación) corre solo en el servidor. La cuota global es de 20 llamadas por día UTC, **reintentos incluidos**, con un contador transaccional en Firestore y reutilización de resultados compatibles. Límites por IP: 30 consultas y 2 generaciones por minuto.
- Ante cuota agotada, fallo del proveedor o contador no disponible, se genera una **plantilla con citas** y se muestra el motivo. No hay cambio automático a un proveedor de pago.
- Conexiones personales (ChatGPT, Claude) existen solo en ejecución local y están deshabilitadas en la API pública.

## Modos de ejecución

| Modo | Acceso (`UMBRAL_AUTH_MODE`) | Persistencia | Notas |
|---|---|---|---|
| Web pública | `public` | Ninguna en servidor; IndexedDB en el navegador | Sin cuentas ni Firebase Auth; escrituras privadas responden 403 |
| Escritorio | `local` (credencial efímera del proceso) | SQLite en `%LOCALAPPDATA%\Umbral` | Funciona sin internet; Gemini solo si hay conexión |
| Desarrollo | `local` | SQLite local | `scripts/start-local.*` o `scripts/dev.*` |
| Pruebas | `dev-header` | Memoria o SQLite temporal | Nunca en producción |

`UMBRAL_OFFLINE=1` impide toda llamada externa.

## Trabajo del usuario y portabilidad

En la web pública el trabajo vive en el IndexedDB de cada navegador, con control de versiones por transacción y sincronización entre pestañas. La **copia JSON** (formato `umbral-workspace`, versión 1) es la misma en web y escritorio; una importación con conflictos nunca reemplaza el trabajo en silencio. También se puede exportar cada caso a Markdown. Exporta una copia antes de borrar los datos del navegador o cambiar de equipo.

## Seguridad e interfaz

- Sin secretos en el repositorio; solo `.env.example`.
- Firestore está cerrado al navegador por sus reglas; la cuenta de servicio vive únicamente en el servidor.
- La API pública no guarda trabajo personal ni confía en `X-Forwarded-For`; la identidad para los límites usa `CF-Connecting-IP` solo si se habilita de forma explícita y, si falta, comparte el límite del socket.
- Escritorio: aislamiento de contexto, sandbox y sin integración de Node en la página; el backend escucha solo en loopback y exige un secreto efímero del proceso.
- **Regla «nada nativo»:** la interfaz no usa controles ni ayudas con apariencia del navegador o del sistema (`<select>`, casillas, números, `<details>`, `<dialog>`, `title`, validación nativa, `alert`/`confirm`). Todo se resuelve con los componentes propios de `apps/web/src/components/ui/controls.tsx` (`Select`, `Checkbox`, `NumberField`, `Disclosure`, `Tooltip`), con teclado según los patrones ARIA, zonas táctiles de al menos 44 px, versión móvil y respeto de `prefers-reduced-motion`. Se comprueba con `scripts/check_no_native_ui.py`, una prueba de integración del guardián y pruebas E2E que recorren la interfaz real.

Para reportar una vulnerabilidad, ver [SECURITY.md](../../SECURITY.md).
