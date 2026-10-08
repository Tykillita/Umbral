<div align="center">

<img src="apps/web/public/brand/icon-256.png" width="80" alt="Umbral owl mark">

# Umbral — De la señal a la decisión

**De la señal a la decisión: una agenda priorizada de noticias, con evidencia, para revisión humana.**

[English](README.md) · **Español**

[![CI](https://github.com/Tykillita/Umbral/actions/workflows/ci.yml/badge.svg?style=flat-square)](https://github.com/Tykillita/Umbral/actions/workflows/ci.yml)
[![Astro](https://img.shields.io/badge/Astro-7-BC52EE?style=flat-square&logo=astro&logoColor=white)](https://astro.build)
[![React](https://img.shields.io/badge/React-19-149ECA?style=flat-square&logo=react&logoColor=white)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org)
[![Node.js](https://img.shields.io/badge/Node.js-24-339933?style=flat-square&logo=nodedotjs&logoColor=white)](https://nodejs.org)
[![Languages](https://img.shields.io/badge/idiomas-EN%20%7C%20ES-52665A?style=flat-square)](README.md)
[![Firebase Hosting](https://img.shields.io/badge/hosting-Firebase%20%2B%20Render-FFCA28?style=flat-square&logo=firebase&logoColor=111)](https://firebase.google.com/products/hosting)
[![MIT](https://img.shields.io/badge/licencia-MIT-5C83B5?style=flat-square)](LICENSE)

<br>

<img src="apps/web/public/brand/social.png" width="720" alt="Tarjeta social de Umbral: una agenda priorizada de cinco viñetas">

<p><a href="https://site-umbral.web.app/app">Abrir la app</a> &bull; <a href="#funciones">Funciones</a> &bull; <a href="#inicio-rápido">Inicio rápido</a> &bull; <a href="#arquitectura">Arquitectura</a> &bull; <a href="#aplicación-de-windows">App de Windows</a> &bull; <a href="#límites-conocidos">Límites conocidos</a> &bull; <a href="SECURITY.md">Política de seguridad</a></p>

<sub>Noticias de Panamá e indicadores oficiales · Interfaz en español · Solo planes gratuitos</sub>

</div>

Umbral nace del reto de hackathon de TVN Media *«De la señal a la decisión»* (2026-10-07 a 2026-10-09). Responde a una pregunta: **¿qué cinco temas merecen revisión editorial para la agenda de Panamá y por qué?**

> Todo lo que produce Umbral es un **borrador o una señal para revisión**. Nada se publica automáticamente, aprobar un borrador **no** es publicarlo y el sistema nunca etiqueta una noticia como verdadera o falsa.

La interfaz está en español. El código y los identificadores están en inglés; el README en inglés refleja este.

## Funciones

- **Agenda priorizada.** Un puntaje transparente y versionado (`scoring-v1`): `P = 30R + 25I + 20U + 15N + 10E` (relevancia, impacto, urgencia, novedad, evidencia). Bajo `[0, 40)`, medio `[40, 70)`, alto `[70, 100]`. El *estado de evidencia* (insuficiente / parcial / suficiente para el borrador) es independiente del puntaje, y una nota replicada por una agencia cuenta como **una** procedencia.
- **Fichas de evidencia.** Cada tema muestra sus fuentes, indicadores oficiales (Banco Mundial), contradicciones, avisos de contenido patrocinado y por qué cada componente vale lo que vale.
- **Borradores con sustento.** Gemini genera un borrador estructurado con citas; si se agota la cuota o falla el proveedor, se genera una **plantilla con citas**. La interfaz indica siempre si el borrador fue *generado por un modelo*, *recuperado* o *construido con plantilla*.
- **Privado por diseño.** La web pública no tiene cuentas. Borradores, versiones, revisiones, impacto y pesos viven en el **IndexedDB** de cada navegador; la API no guarda trabajo personal. Se puede exportar y restaurar una copia JSON portable, o exportar a Markdown.
- **Clasificación local.** Las noticias se clasifican con el modelo abierto [Laya](https://huggingface.co/convaiinnovations/laya) en CPU, fijado a una revisión concreta. La aplicación de Windows incluye el modelo y funciona sin conexión.
- **Actualización diaria.** Un workflow programado construye un snapshot verificado (manifest SHA-256, sin fixtures) y lo publica como feed; la API y la app de escritorio lo descargan solo cuando cambia y conservan el último snapshot válido si algo falla.
- **Interfaz hecha a mano.** Sin controles nativos del navegador: selectores, casillas, campos numéricos, desplegables y ayudas son componentes propios y accesibles con teclado (un guardián estático y pruebas E2E lo aseguran).

## Arquitectura

```
Fuentes públicas ─► pipeline (Laya, Python 3.12) ─► snapshot verificado + SHA-256
                                                        │
                    ┌───────────────────────────────────┤
                    ▼                                   ▼
          Firebase Hosting                       Render (FastAPI)
          web estática + feed de datos           API pública sin estado
                    │                            Firestore: solo la cuota diaria de Gemini
                    ▼
          Navegador (Astro + React)  ── IndexedDB: tus borradores, revisiones y pesos

          Windows (Electron) incluye API + pipeline + PyTorch CPU + Laya, SQLite en %LOCALAPPDATA%\Umbral
```

Más detalle en [docs/public/ARCHITECTURE.md](docs/public/ARCHITECTURE.md). Contratos: [esquema del snapshot](docs/contracts/snapshot-schema.md), [API](docs/contracts/api-draft.md) y [API pública](docs/contracts/api-public.md), además de `apps/api/openapi.json`.

## Estructura del repositorio

```
apps/api/      servicio FastAPI (+ openapi.json)      pipeline/   ingesta, validación, clasificación, agrupación
apps/web/      interfaz Astro + React                 data/       snapshots verificados (sin datos crudos)
apps/desktop/  Electron + instalador NSIS (Windows)   eval/       benchmark de desarrollo y herramientas de métricas
tests/         pruebas de integración y E2E           scripts/    instalación, arranque local, comprobaciones, despliegue
docs/          documentación pública y contratos
```

## Inicio rápido

Necesitas [`uv`](https://docs.astral.sh/uv/) (descarga Python 3.12 sin tocar el de tu sistema) y Node 24. La web declara `node@24` como dependencia de desarrollo, así que no hace falta cambiar tu Node global.

```bash
git clone https://github.com/Tykillita/Umbral.git && cd Umbral
scripts/setup.sh          # Windows: scripts\setup.ps1  (añade --laya / -Laya para instalar el runtime del modelo)
scripts/start-local.sh    # Windows: scripts\start-local.ps1
```

`start-local` compila la web y la sirve junto con la API en <http://localhost:8000> con el snapshot verificado de `data/snapshots/CURRENT`. Con `UMBRAL_OFFLINE=1` (o `--offline` / `-Offline`) se bloquea toda llamada externa.

Para desarrollar usa `scripts/dev.sh` (API en :8000, Astro en :4321).

## Configuración

Solo se versionan los archivos `.env.example`; nunca subas claves reales (`apps/api/.env.example`, `apps/web/.env.example`). Las variables `PUBLIC_*` quedan embebidas en el navegador y no son secretos.

| Variable | Para qué |
|---|---|
| `UMBRAL_AUTH_MODE` | `public` (web alojada, sin cuentas) · `local` (escritorio/desarrollo, un usuario) · `dev-header` (pruebas) |
| `UMBRAL_PERSISTENCE` | `none` (API pública) · `sqlite` (escritorio/local) · `memory` (pruebas) |
| `UMBRAL_OFFLINE` | `1` = sin llamadas externas |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Nivel gratuito de Gemini, sin facturación; si falla, plantilla |
| `GEMINI_GLOBAL_CALLS_PER_DAY` | Tope global duro (máximo 20 por día UTC, reintentos incluidos) |
| `FIREBASE_PROJECT_ID`, `GOOGLE_APPLICATION_CREDENTIALS` | Solo en servidor, para el contador durable de cuota |
| `UMBRAL_CORS_ORIGINS`, `UMBRAL_CORS_PREVIEW_PROJECT` | Orígenes web permitidos y canales de vista previa de Firebase |
| `PUBLIC_API_URL`, `PUBLIC_API_MODE`, `PUBLIC_AUTH_MODE` | Compilación web: origen de la API, comportamiento ante errores y modo de acceso |

## Pruebas

```bash
uv run --no-project python scripts/check_repo.py --strict        # secretos y archivos prohibidos
uv run --no-project python scripts/check_public_files.py         # solo archivos publicables, sin rutas personales
uv run --no-project python scripts/check_no_native_ui.py         # regla de controles propios
(cd apps/api && uv run --extra firebase pytest && uv run --extra firebase ruff check . && uv run --extra firebase mypy src \
  && uv run --extra firebase python scripts/export_openapi.py --check)
(cd pipeline && uv run ruff check . && uv run pytest)            # sin red ni PyTorch
(cd apps/web && pnpm install --frozen-lockfile && pnpm check && pnpm test && pnpm build)
scripts/test.sh                                                   # todo, con integración y E2E de Playwright
```

Qué se ejecutó, cuándo y con qué resultado queda en [docs/public/VALIDATION.md](docs/public/VALIDATION.md). Una cita válida en su estructura no prueba que la afirmación esté sustentada, y las pruebas automáticas no sustituyen el juicio editorial humano.

## Despliegue

Cada pull request recibe una vista previa en Firebase Hosting; al integrar en `main` se despliega el mismo commit en Render, se verifica y solo entonces se publica Firebase Hosting. Todo corre en planes gratuitos (Firebase Spark, Render Free, nivel gratuito de Gemini) y dentro de sus cuotas. Ver [docs/public/DEPLOYMENT.md](docs/public/DEPLOYMENT.md).

## Aplicación de Windows

`apps/desktop` construye un instalador NSIS por usuario para Windows 10/11 x64 que incluye la API, el pipeline, PyTorch CPU y los pesos de Laya: no requiere Python, Node ni descargar el modelo en el equipo de destino. El instalador no está firmado, así que Windows puede mostrar un aviso. Ver [apps/desktop](apps/desktop) y [docs/public/DEPLOYMENT.md](docs/public/DEPLOYMENT.md#windows-app).

## Límites conocidos

- Las salidas se basan en **titulares y metadatos**, no en el texto completo del artículo.
- Las probabilidades del clasificador no están calibradas. La calidad de la clasificación, el sustento de las afirmaciones y Precision@5 requieren **revisión humana** y no se presentan como calidad editorial validada.
- El snapshot actual es **provisional**: no se ha entregado el paquete oficial congelado de noticias.
- La corroboración independiente es escasa en el corpus recolectado; el contenido patrocinado se marca y se limita.
- Render Free se duerme tras 15 minutos sin uso, por lo que la primera petición puede tardar cerca de un minuto; la interfaz muestra un estado de preparación y un botón de reintento.
- Este MVP no incluye datos de audiencia, rating ni modalidad bancaria.

## Seguridad

Consulta [SECURITY.md](SECURITY.md) para reportar una vulnerabilidad. Trata el texto de cualquier fuente como dato, nunca como instrucción.

## Licencia

[MIT](LICENSE) © Umbral contributors. Los componentes de terceros conservan sus licencias; la tarjeta y los términos del modelo Laya se incluyen en el instalador de escritorio.
