# Umbral — interfaz editorial

Astro estático con una isla React en `/app/`: Agenda, Ficha, Borradores, Fuentes y evaluación y asistente. Los tipos en `src/lib/api/schema.d.ts` se generan desde `../api/openapi.json`; no se editan a mano.

## Desarrollo y build

Usa Node 24 LTS. La dependencia local `node@24.21.0` permite ejecutar los scripts sin cambiar el Node global. En esta máquina Windows, pnpm necesita Git Bash como `script-shell` de la sesión:

```powershell
cd apps/web
$env:npm_config_script_shell = 'C:\Program Files\Git\bin\bash.exe'
npx.cmd -y pnpm@10.33.0 install --frozen-lockfile
npx.cmd -y pnpm@10.33.0 run gen:api
npx.cmd -y pnpm@10.33.0 run check
npx.cmd -y pnpm@10.33.0 run test
npx.cmd -y pnpm@10.33.0 run dev
```

La API de desarrollo usa `http://localhost:8000`; Astro en `http://localhost:4321` reenvía `/api`. Cambia el destino con `UMBRAL_API_PROXY`. Para ejecutar toda la aplicación local, consulta los scripts `start-local.ps1` / `start-local.sh` en la raíz.

Build local con API real y sin Firebase, incluso si `.env` contiene configuración Firebase:

```powershell
$env:PUBLIC_API_MODE = 'live'
$env:PUBLIC_API_URL = ''
$env:PUBLIC_AUTH_MODE = 'local'
npx.cmd -y pnpm@10.33.0 run build
```

Alternativa directa verificada para dependencias ya instaladas:

```powershell
.\node_modules\node\bin\node.exe node_modules/astro/bin/astro.mjs build
.\node_modules\node\bin\node.exe node_modules/@astrojs/check/bin/astro-check.js
.\node_modules\node\bin\node.exe node_modules/vitest/vitest.mjs run
```

`dist/` contiene `/` y `/app/`. FastAPI sirve ese build en modo local. Las variables `PUBLIC_*` quedan fijadas **al construir**: cambiar el entorno del servidor después no modifica la autenticación del bundle.

## Movimiento de cómic

Las animaciones de `/app/` son decorativas, breves y no cambian el comportamiento: usan CSS más Web Animations API y respetan `prefers-reduced-motion` (con movimiento reducido no se anima nada y los cambios son inmediatos).

- `src/lib/motion.ts` centraliza duraciones, curvas y reproductores (encabezado 260 ms, tarjetas 280 ms escalonadas cada 40 ms con tope de 480 ms, pulsación 160 ms, trazos 180 ms, asistente 240/140 ms, despliegues 180 ms, avisos 220 ms). Cambia los tiempos solo ahí.
- `src/lib/useMotion.ts` aporta los hooks `useEntrance` (una entrada por sección y `topicId`, sin remontar formularios), `useRevealNew` («Ver más» anima solo las tarjetas nuevas) y `useDisclosureMotion`.
- `src/lib/interactions.ts` instala una sola vez los oyentes globales de pulsación y trazos de impacto; los paneles usan `Disclosure`; nunca llama a `preventDefault` ni retrasa un clic.
- Marcas en el DOM: `data-motion="heading"|"card"`, `data-motion-id` (tarjetas de «Ver más») y `data-press-host` (fila que se comprime cuando el enlace va estirado). Los trazos (`[data-ink]`) son `aria-hidden` y no reciben punteros.
- Las E2E que miden geometría esperan con `settle_motion` (`tests/e2e/helpers.py`) a que terminen las animaciones finitas.

## API y autenticación

| Variable | Valor | Comportamiento |
|---|---|---|
| `PUBLIC_API_MODE` | `live` | Fallos visibles; no reemplaza la API por datos simulados. Predeterminado en build. |
| `PUBLIC_API_MODE` | `mock` | Datos de demostración con banner explícito. |
| `PUBLIC_API_MODE` | `auto` | Prueba la API y usa mock etiquetado si no responde. Predeterminado en desarrollo. |
| `PUBLIC_AUTH_MODE` | `public` | Entrada sin Firebase ni `Authorization`; trabajo privado en IndexedDB por navegador. |
| `PUBLIC_AUTH_MODE` | `local` | Usuario único; omite el SDK y las llamadas Firebase aunque haya variables Firebase guardadas. |
| `PUBLIC_AUTH_MODE` | `firebase` | Exige los cuatro campos Firebase y una sesión anónima válida. Un error bloquea el arranque o la solicitud, sin convertirse en usuario local. |
| `PUBLIC_AUTH_MODE` | `auto` | Predeterminado. Sin campos Firebase usa local; con cualquier campo exige configuración Firebase completa. |

Para Hosting/Render usa `PUBLIC_API_MODE=live` y `PUBLIC_AUTH_MODE=public`. El backend usa `AUTH_MODE=public`; las ediciones no se persisten en la nube. `PUBLIC_API_URL` explícita tiene prioridad. Si está vacía, el navegador lee `/public-config.json` con `{ "schemaVersion": 1, "apiUrl": "https://<servicio>.onrender.com" }`. Solo acepta HTTPS de Render, sin credenciales, rutas ni parámetros. El perfil faltante se admite únicamente en localhost para pruebas del servidor del mismo origen; Hosting muestra un error visible y permite reintentar.

Builds independientes con Node 24 incluido:

```powershell
$env:PUBLIC_API_MODE = 'live'; $env:PUBLIC_AUTH_MODE = 'public'; $env:PUBLIC_API_URL = ''
.\node_modules\node\bin\node.exe node_modules/astro/bin/astro.mjs build --outDir dist-public
$env:PUBLIC_AUTH_MODE = 'local'
.\node_modules\node\bin\node.exe node_modules/astro/bin/astro.mjs build --outDir dist
```

El primer arranque público reintenta errores de conexión/502/503/504 durante un máximo de 90 segundos con estado visible y botón de reintento. Una respuesta HTML o JSON inválido falla claramente; nunca activa datos simulados. Firebase sigue como modo explícito heredado de verificación y no participa en la publicación pública. El build retira conceptos/prompts de marca y su README de la salida, conservando las fuentes originales.

## Espacio de trabajo y escritorio

IndexedDB guarda versiones con transacciones CAS (`expectedVersion`), y `BroadcastChannel` refresca los datos entre pestañas. El editor conserva texto pendiente y su versión inicial cuando otra pestaña guarda; un conflicto exige recarga explícita. Cada caso conserva ficha, citas y corte originales aunque cambie el snapshot. La API recalcula el puntaje con esa evidencia archivada. Si no responde, se identifica el puntaje del corte guardado; la copia JSON y la exportación conservan las fuentes.

En Fuentes está la copia JSON v1 (`umbral-workspace`), compatible con el espacio SQLite del escritorio. Guarda casos, borradores, historia de revisión, asignaciones de impacto y pesos con responsables y motivos. La importación valida toda la copia antes de una transacción, fusiona casos nuevos y rechaza conflictos sin cambios parciales. Usa pegado o arrastre del JSON, con controles propios. Los errores de cuota o almacenamiento bloqueado indican que el cambio no se guardó.

Las consultas y el contexto mínimo de ranking se envían a la API. La validación de una edición/revisión envía temporalmente solo el borrador vigente y las fuentes conservadas; no transmite textos antiguos ni historial completo. Los nombres de responsables se conservan en el dispositivo y se omiten del contexto usado para puntuar.

La build local usa la API SQLite del mismo origen. Cuando Electron expone `window.umbralDesktop`, Fuentes muestra actualización de noticias y reclasificación local de Laya, con estado del proceso y errores. El token efímero del bridge se envía únicamente al backend del mismo origen en loopback y no viaja por redirecciones. El modelo y el instalador se verifican en `apps/desktop`.


## Validación y evidencia

`pnpm test` verifica arranque/reintento, configuración pública, dos navegadores, dos pestañas/CAS, archivo, copia/importación atómica, errores IndexedDB, token de escritorio y componentes existentes. Son fixtures explícitos; no prueban Gemini ni Firebase remotos. Los recibos con fecha, comandos y huella se guardan en `.qa/`.

Las cuatro pruebas heredadas `DraftsSources.live.test.tsx` exigen un servidor con snapshot sintético de pruebas y SQLite propia. Están excluidas por defecto. Para pedirlas define `UMBRAL_LIVE_TESTS=1` y `UMBRAL_API_URL=http://127.0.0.1:<puerto>` antes de `pnpm test`; una API ausente provoca fallo. No se cuentan como aprobadas cuando faltan sus requisitos.

El recorrido con datos reales se verifica con Playwright Python, usando el entorno de pruebas del workspace:

```powershell
# Desde la raíz; API de QA propia, offline, auth local y snapshot real con Laya.
$env:PLAYWRIGHT_BROWSERS_PATH = (Resolve-Path tests/.browsers).Path
$env:PYTHONUTF8 = '1'
.\tests\.venv\Scripts\python.exe apps/web/scripts/verify-ui.py --url http://127.0.0.1:8011
```

El script exige `offline=true` y API local, bloquea solicitudes del navegador fuera de ese origen y no llama a Gemini. Comprueba las cuatro vistas a 1440/390/320 px, controles etiquetados, foco de navegación, diálogo móvil, citas/abstención, plantilla validada, edición/guardar/exportación y recuperación de un error 503. Sus ediciones y transición `en_revision` se identifican como automatización de QA y deben usar una SQLite de prueba. Guarda el informe y capturas regenerables en `.qa/` (ignorado por Git).

La UI conserva las categorías y el ranking de la API, incluso cuando Laya se equivoca. El aviso visible explica que la clasificación no tiene calibración validada y que los porcentajes del modelo no equivalen a confianza editorial. Confirmar clasificación, impacto y sustento humano sigue siendo trabajo editorial pendiente.
