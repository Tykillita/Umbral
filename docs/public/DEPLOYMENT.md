# Despliegue

Umbral se publica en planes gratuitos: **Firebase Hosting** (Spark) para la web y el feed de datos, **Render Free** para la API, **Firestore** solo para el contador de cuota de Gemini y el **nivel gratuito de Gemini** sin facturación. Nada de lo que sigue requiere un método de pago; si una cuota se agota, el sistema cae a una plantilla con citas en lugar de pasar a un proveedor de pago.

## Flujo de publicación

```
rama ─► Pull request ─► CI (higiene, API, pipeline, web, integración y E2E)
                      └► vista previa en Firebase Hosting (canal pr-<n>, caduca a los 7 días)

merge a main ─► CI aprobada ─► workflow «Despliegue»
                  1. Render despliega ESE commit (hook con el SHA)
                  2. se espera a que /api/v1/health informe ese SHA, en modo público, con datos Laya íntegros y CORS correcto
                  3. se compila y publica Firebase Hosting
                  4. prueba online contra las URL reales (scripts/verify_hosted.py)
```

- GitHub Actions es el **único orquestador**. Render tiene los despliegues automáticos desactivados (`autoDeployTrigger: "off"`) y solo despliega cuando recibe el hook con un commit concreto.
- Si el paso 2 falla, **Firebase Hosting no se actualiza**: la web publicada sigue apuntando a la API anterior, que sigue funcionando.
- Un despliegue de código **no retrocede los datos**: parte del feed ya publicado (`/data/current.json` y su historial) y solo usa el snapshot versionado la primera vez.
- Los recibos (`render-receipt.json`, `hosted-receipt.json`) se conservan como artefactos de la ejecución durante 30 días.

## Configuración única

Estos pasos se hacen una vez, a mano, por quien administra el repositorio. Ningún valor secreto se guarda en el repositorio.

### GitHub

| Tipo | Nombre | Contenido |
|---|---|---|
| Variable de Actions | `PUBLIC_API_URL` | Origen HTTPS de la API (`https://<servicio>.onrender.com`) |
| Secreto de Actions | `RENDER_DEPLOY_HOOK_URL` | Deploy hook del servicio de Render (`https://api.render.com/deploy/...`) |
| Secreto de Actions | `FIREBASE_DEPLOY_SERVICE_ACCOUNT` | Cuenta de servicio con permiso solo para publicar Hosting en `site-umbral` |
| Variable de Actions (después) | `UMBRAL_DAILY_ENABLED`, `PRODUCTION_RELEASE_REF` | Activan el workflow diario de datos; ver más abajo |

Protege `main`: pull request obligatorio y comprobaciones de CI requeridas. Los secretos no se exponen a PRs de forks (los workflows usan `pull_request`, nunca `pull_request_target`) y la vista previa solo se construye para ramas del propio repositorio.

### Render

1. Crea el servicio web **Free** desde el Blueprint `render.yaml` (raíz del repositorio), rama `main`.
2. Comprueba que **Auto-Deploy** está desactivado y copia el *Deploy Hook* al secreto de GitHub.
3. Escribe en el panel `GEMINI_API_KEY` (nivel gratuito, sin facturación vinculada).
4. Sube la cuenta de servicio de Firebase del backend como **Secret File** `firebase-service-account.json` (ruta `/etc/secrets/`). Es una cuenta distinta de la de despliegue y solo la usa el servidor para el contador de cuota.
5. Revisa que `UMBRAL_CORS_ORIGINS` y `UMBRAL_CORS_PREVIEW_PROJECT` en el Blueprint coinciden con tu proyecto Firebase.

Valores relevantes del Blueprint: Python `3.12.14`, `uv==0.12.7`, instalación congelada con el extra `firebase`, `UMBRAL_AUTH_MODE=public`, `UMBRAL_PERSISTENCE=none`, `UMBRAL_LOCAL_MODE=false`, `UMBRAL_STRICT_INTEGRITY=1`, `UMBRAL_OFFLINE=0`, `UMBRAL_ALLOW_FIXTURE=false`.

### Firebase

- Proyecto `site-umbral`, Hosting y Firestore creados. Las reglas de Firestore deniegan todo acceso desde navegadores (`firestore.rules`); solo el servidor, con su cuenta de servicio, escribe el contador.
- Comprueba que las reglas no estén en modo de prueba.

## Vistas previas

Cada PR del propio repositorio publica un canal `pr-<número>` (caduca a los 7 días) con la API real compartida y deja la URL en el **resumen de la ejecución** (no se comenta en el PR). Los orígenes de esos canales se permiten en la API mediante `UMBRAL_CORS_PREVIEW_PROJECT`, que solo acepta `<proyecto>--pr-<n>-<hash>.web.app|firebaseapp.com`.

Las vistas previas **usan recursos reales** (la misma API y su cuota de Gemini); no son un entorno aislado.

## Verificación manual

```bash
python3 scripts/wait_for_deploy.py --api-url https://<servicio>.onrender.com --sha <SHA de 40 caracteres> \
  --web-origin https://site-umbral.web.app
python3 scripts/verify_hosted.py --web-url https://site-umbral.web.app --api-url https://<servicio>.onrender.com \
  --expected-snapshot-file .production/candidate-id
```

`wait_for_deploy.py` exige: SHA desplegado, `status: ok`, modo público sin persistencia, datos Laya sin fixtures con integridad verificada y CORS del origen de Hosting. `verify_hosted.py` comprueba además portada, aplicación, descubrimiento de la API para escritorio, descriptor de datos, agenda, ficha con evidencia, consulta en español, plantilla válida y que la escritura privada devuelve 403. Ninguno llama a Gemini real ni acredita revisión humana.

## Arranque en frío de Render Free

Render Free se duerme tras 15 minutos sin tráfico y su disco es efímero. La primera petición puede tardar cerca de un minuto: la interfaz reintenta durante hasta 90 segundos, muestra un estado de preparación y ofrece un reintento manual. El trabajo del usuario no se pierde porque vive en el navegador.

## Recuperar el último despliegue válido

- **Código y API:** ejecuta el workflow **Despliegue** manualmente («Run workflow», rama `main`) con el SHA de un commit anterior que pasó la CI. Render despliega ese commit, se verifica y se vuelve a publicar Hosting.
- **Solo Hosting:** en la consola de Firebase, restaura una versión anterior desde el historial de Hosting.
- **Solo la API:** en Render, vuelve a desplegar un deploy anterior desde su historial.
- **Datos:** el feed conserva los últimos siete snapshots válidos; la API y el escritorio conservan el último válido si una actualización falla.

## Actualización de datos cada 6 horas

El workflow `daily-data.yml` («Datos de Umbral (cada 6 horas)») se ejecuta a las **00:17, 06:17, 12:17 y 18:17 UTC** (19:17, 01:17, 07:17 y 13:17 en Panamá) y también a demanda. GitHub puede retrasar los cron programados varias horas; el botón «Actualizar noticias» de la web y «Run workflow» lo compensan. Con el artefacto Laya publicado (abajo) una ejecución tarda unos 10–25 minutos y el límite del job es de 60.

Mientras no haya un corte de menos de 36 horas, la API (`UMBRAL_HIDE_STALE_SNAPSHOT_HOURS=36` en `render.yaml`) no muestra noticias viejas: la agenda queda vacía con un mensaje claro hasta que llegue uno vigente.

### Modelo Laya calibrado

El job ya no reentrena Laya en cada ejecución (eran ~2 h y fallaba la compuerta de calibración o el límite de tiempo). Descarga el **artefacto exacto** publicado como asset de una release de GitHub (gratis en un repositorio público), comprueba su SHA-256 y sus pesos con `scripts/laya_artifact.py fetch`, y `eval/prepare_laya_production_model.py` lo verifica sin entrenar. Se declara en `eval/laya-calibrated-artifact.json`.

Publicarlo es una acción de una sola vez, tuya (el script no sube nada):

```powershell
uv run --no-project python scripts/laya_artifact.py package --model-dir .production/laya-model --out .production/laya-calibrated.tar
gh release create laya-calibrated-v1 .production/laya-calibrated.tar --repo Tykillita/Umbral --title "Laya calibrada" --notes "Artefacto calibrado del job de datos."
```

El script y el descriptor se toman del commit del propio workflow (checkout parcial en `.workflow-tools`), mientras el código de producción sigue anclado a `PRODUCTION_RELEASE_REF`; la release `laya-calibrated-v1` es un *pre-release* para que el actualizador de escritorio no la confunda con una versión de la app. Después haz commit de `eval/laya-calibrated-artifact.json` (pasa a `status: published` con su SHA-256). Mientras diga `pending`, el job falla en segundos con un mensaje claro; se puede lanzar a mano con `train=true` para reentrenar dentro del job (~2 h, límite de 150 min).

El workflow está **desactivado** hasta que se defina `UMBRAL_DAILY_ENABLED=true` tras verificar el primer despliegue. Necesita además `PRODUCTION_RELEASE_REF` (SHA o tag verificado) y `PUBLIC_API_URL`.

Extrae con 48 horas de solape y una ventana móvil de 30 días, clasifica con Laya CPU (revisión fijada), verifica el candidato y lo publica en Hosting sin activar el anterior hasta validar hashes y referencias. Un fallo de fuente, de Laya o de integridad aborta el candidato: nunca se sustituye por un clasificador de referencia ni por datos parciales. Se recomienda comprobar dos ciclos completos antes de darlo por estable.

### Botón «Actualizar noticias»

En la agenda, «Hoy» trae al instante los titulares de TVN y Bing News de las últimas 24 horas, **sin clasificar** (rotulados así, fuera de la agenda y del puntaje), y pide al workflow `daily-data.yml` que clasifique un corte nuevo. La web dice con claridad que la clasificación puede tardar entre 15 y 25 minutos y la agenda se actualiza sola cuando llega el corte.

Para que pueda **pedir la clasificación** hace falta un token de GitHub; crearlo y guardarlo es una acción tuya y nunca va al repositorio:

1. GitHub → *Settings → Developer settings → Fine-grained personal access tokens → Generate*: repositorio `Tykillita/Umbral` únicamente, permiso **Actions: Read and write**, sin ningún otro, con caducidad.
2. Render → servicio de la API → *Environment* → `UMBRAL_GITHUB_DISPATCH_TOKEN` = el token (secreto; `render.yaml` solo declara `sync: false`).

Salvaguardas: máximo 3 pulsaciones por minuto y usuario, un enfriamiento de 30 minutos entre solicitudes de clasificación (`UMBRAL_NEWS_REFRESH_MIN_INTERVAL_S`), no lanza otra si ya hay una ejecución en curso o en cola, solo habla con `api.github.com` y el token no se registra ni se devuelve. Sin token, el botón sigue mostrando los titulares sin clasificar y avisa de que no puede clasificar.

## Cuotas

Todo se mantiene dentro de los planes gratuitos: Hosting Spark, minutos de Actions de un repositorio público, Render Free, Firestore Spark (un documento de contador por día) y Gemini Free Tier. Si una cuota se agota, la consecuencia es degradar a plantilla o esperar, nunca un cobro.

## Windows app

`apps/desktop` construye un instalador NSIS por usuario para Windows 10/11 x64 con Electron. Incluye Python, FastAPI, el pipeline, PyTorch CPU y los pesos de Laya, así que no necesita Python, Node ni descargas de modelos en el equipo de destino.

```powershell
cd apps/desktop
uv sync --locked
./build.ps1 -Installer
```

El build usa el Node 24 de `apps/web`, verifica el snapshot y el checkpoint de Laya, empaqueta el motor con PyInstaller y genera el SHA-256 del instalador. Los datos del usuario viven en `%LOCALAPPDATA%\Umbral` (SQLite, snapshots, preferencias y respaldos); los recursos instalados son de solo lectura y se hace un respaldo antes de abrir una versión nueva.

Las versiones estables se publican en GitHub Releases al crear un tag `vX.Y.Z` que coincida con `apps/desktop/package.json`. El workflow `release-desktop.yml` compila el instalador NSIS para Windows, publica `latest.yml` y los artefactos que necesita Electron para actualizar, y adjunta el SHA-256. La app empaquetada comprueba releases estables al iniciar y cada 24 horas; descarga en segundo plano y muestra un aviso propio de Umbral. Se instala al elegir **Reiniciar e instalar** o al cerrar la aplicación después de que la descarga haya terminado. No se consultan borradores ni versiones preliminares. Los builds locales nunca publican.

Las instalaciones anteriores a la primera versión con updater deben instalar manualmente ese instalador una vez; no contienen el código que consulta las releases. Las siguientes versiones podrán llegar automáticamente y el instalador por usuario conserva `%LOCALAPPDATA%\Umbral`.

La publicación usa el `GITHUB_TOKEN` temporal de Actions con permiso `contents: write`; no requiere un secreto adicional. El tag sigue siendo una decisión explícita para cada hito. La release debe conservar el instalador y `latest.yml` para que las instalaciones existentes puedan actualizarse.

Con conexión la app descarga el snapshot diario y usa la generación pública de Gemini; sin conexión funciona con los datos disponibles y plantillas con citas.

El instalador **no está firmado** (no hay certificado de pago), por lo que Windows puede mostrar un aviso. Publica siempre el SHA-256 junto al instalador. Una instalación y actualización en un Windows limpio es una comprobación aparte que no se da por hecha por el solo hecho de que el build funcione en el equipo de desarrollo.
