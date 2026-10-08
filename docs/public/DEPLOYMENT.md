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

## Actualización diaria de datos

El workflow `daily-data.yml` se ejecuta a las **06:17 de Panamá** (11:17 UTC) y también a demanda. Está **desactivado** hasta que se defina `UMBRAL_DAILY_ENABLED=true` tras verificar el primer despliegue. Necesita además `PRODUCTION_RELEASE_REF` (SHA o tag verificado) y `PUBLIC_API_URL`.

Extrae con 48 horas de solape y una ventana móvil de 30 días, clasifica con Laya CPU (revisión fijada), verifica el candidato y lo publica en Hosting sin activar el anterior hasta validar hashes y referencias. Un fallo de fuente, de Laya o de integridad aborta el candidato: nunca se sustituye por un clasificador de referencia ni por datos parciales. Se recomienda comprobar dos ciclos completos antes de darlo por estable.

## Cuotas

Todo se mantiene dentro de los planes gratuitos: Hosting Spark, minutos de Actions de un repositorio público, Render Free, Firestore Spark (un documento de contador por día) y Gemini Free Tier. Si una cuota se agota, la consecuencia es degradar a plantilla o esperar, nunca un cobro.

## Windows app

`apps/desktop` construye un instalador NSIS por usuario para Windows 10/11 x64 con Electron. Incluye Python, FastAPI, el pipeline, PyTorch CPU y los pesos de Laya, así que no necesita Python, Node ni descargas de modelos en el equipo de destino.

```powershell
cd apps/desktop
uv sync --locked
./build.ps1 -Installer
```

El build usa el Node 24 de `apps/web`, verifica el snapshot y el checkpoint de Laya, empaqueta el motor con PyInstaller y muestra el SHA-256 del instalador. Los datos del usuario viven en `%LOCALAPPDATA%\Umbral` (SQLite, snapshots, preferencias y respaldos); los recursos instalados son de solo lectura y se hace un respaldo antes de abrir una versión nueva. La actualización de la aplicación es manual. Con conexión descarga el snapshot diario y usa la generación pública de Gemini; sin conexión funciona con los datos disponibles y plantillas con citas.

El instalador **no está firmado** (no hay certificado de pago), por lo que Windows puede mostrar un aviso. Publica siempre el SHA-256 junto al instalador. Una instalación y actualización en un Windows limpio es una comprobación aparte que no se da por hecha por el solo hecho de que el build funcione en el equipo de desarrollo.
