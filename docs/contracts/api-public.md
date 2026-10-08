# API pública y espacio de trabajo local

Contrato adicional a `api-draft.md`, modelos en `apps/api/src/umbral_api/public_models.py` y esquemas completos en `apps/api/openapi.json`.

## Ejecución pública

`UMBRAL_AUTH_MODE=public`, `UMBRAL_LOCAL_MODE=0`, `UMBRAL_PERSISTENCE=none`. No requiere Firebase Auth. La identidad se utiliza únicamente para limitar solicitudes por IP; nunca identifica un espacio editorial del servidor. Las operaciones antiguas de escritura y las conexiones personales devuelven 403. `GET /health`, `/snapshot` y `/rules` están disponibles sin autenticación.

Todos los POST siguientes están bajo `/api/v1/public`. Reciben `context`:

La identidad de los límites usa el socket por defecto. `UMBRAL_TRUST_CLOUDFLARE_IP=1` solo es válido con `public` y `LOCAL_MODE=0`, cuando el operador garantiza que todo el tráfico llega por un edge que sobrescribe `CF-Connecting-IP`. Se acepta únicamente una dirección IPv4/IPv6 válida, normalizada; cabecera ausente, inválida, con lista, zona IPv6 o duplicada vuelve al socket. `X-Forwarded-For` nunca se utiliza. Uvicorn debe arrancar con `--no-proxy-headers`, sin confiar en `*`. Si la cabecera CF no llega, los visitantes del mismo proxy comparten el límite: la cuota sigue cerrada ante fallos y no se inventan identidades para evitarla.

[Render documenta el tráfico entrante por Cloudflare y que el socket ve el proxy](https://render.com/articles/how-render-handles-ddos-attacks). [Cloudflare documenta `CF-Connecting-IP` en edge→origin y recomienda su formato de una sola IP](https://developers.cloudflare.com/fundamentals/reference/http-headers/). La entrega de esa cabecera hasta la aplicación de Render es una hipótesis de configuración que debe comprobarse en el servicio alojado; la prueba local no la acredita.

```json
{"snapshotId":"YYYYMMDD-hash8","weights":{"R":30,"I":25,"U":20,"N":15,"E":10},"rulesVersion":"scoring-v1","topicOverrides":[{"topicId":"evt_...","status":"en_revision","evidenceConfirmed":null,"primarySourceConfirmed":false,"primarySourceReason":null,"impact":null}]}
```

`weights`, `rulesVersion` y los campos editoriales son opcionales. Los pesos son enteros 0–100, exactamente R/I/U/N/E y suman 100. `topicOverrides` también admite `evidenceConfirmedBy` y `primarySourceConfirmedBy`; una confirmación primaria exige motivo. El repositorio de contexto vive únicamente durante la petición. Corpus e índices se comparten y no se reconstruyen por visitante.

| Operación | Cuerpo adicional | Respuesta |
|---|---|---|
| `POST /agenda` | `filters`: limit, category, evidence, band, reviewStatus, q, includeComponents, scope | `TopicsResponse` existente |
| `POST /topics/{id}` | Ninguno | `TopicDetail` existente, `case.persisted=false` |
| `POST /queries` | question, topicId opcional, limit | `QueryResponse` existente. En `answer`, `[n]` remite a la n-ésima evidencia distinta de `citations` (por orden de aparición); un `[n]` dentro de «comillas» es texto de una fuente; con `followUp` (el `followUpContext` de la respuesta anterior: `snapshotId`, `intent`, `topicIds`, `evidenceIds`, `countries`, `indicators`, `years`, solo identificadores y nunca texto) una frase de continuación («¿Y en Colombia?», «¿Cuáles son las fuentes del segundo?») se resuelve por reglas; si no es una continuación se ignora el contexto, y si no se puede resolver se pide aclaración. La respuesta añade `resolvedQuestion`, `followUpContext` y `followUpSuggestions` |
| `POST /queries/compose` | mismo cuerpo que `/queries` | `ComposeResponse`: `response` (la respuesta redactada o, si falló, la de reglas), `answerMode` (`modelo` \| `reglas`), `rulesAnswer`, `provider`, `model`, `fallbackReason`, `fallbackDetail`, `usage`, `attempts` (llamadas al modelo), `notices`. Opcional y por pregunta: solo redacta respuestas con fuentes (no abstenciones ni contradicciones); un modelo reescribe usando únicamente las fuentes ya citadas y el código valida ids, campos, pasajes literales, cifras, instrucciones y secretos (un reintento con la retroalimentación). Cuenta contra la cuota diaria de Gemini (global en modo público; los resultados idénticos se reutilizan) y ante cualquier fallo devuelve la respuesta por reglas con el motivo |
| `POST /drafts` | topicId, provider (`auto`, `gemini` o `plantilla`) | `{draft:DraftRecord,notices:string[],evidence:ArchivedEvidence}` |
| `POST /validate` | topicId, package opcional, evidence opcional, case y review opcionales | `{package:EditorialPackage\|null,validation:ValidationReport\|null,case:CaseView\|null}` |

`ArchivedEvidence` = `{snapshotId,topicId,articles:EvidenceArticle[],officialContext:OfficialContext,cutoffUtc?:datetime}`. `TopicDetail` añade `cutoffUtc` para conservar el corte original. Agenda/consulta/generación con un snapshot diferente devuelven 409 con `details.currentSnapshotId`. Ficha y validación admiten `evidence` archivada con el snapshot original; ambos identificadores deben coincidir. La ficha recalcula score/evidencia/acción con los pesos y overrides del dispositivo sobre las fuentes originales. El validador verifica citas y formato, no acredita la autenticidad de una copia importada.

Para revisión, enviar `case` y el `ReviewRequest` existente. Se recalcula la validación del borrador recibido y se aplican las mismas transiciones que en local. Devuelve versión +1 e historial recibido más el evento nuevo, `persisted=false`; el navegador realiza su propia transacción/CAS para guardarlo. Puede enviar solo el borrador vigente e `history:[]` y fusionar el evento nuevo con su historial privado. Transiciones sin borrador pueden enviar `package:null`. Nunca se guardan el caso, sus autores ni comentarios en la API pública.

Consultas: máximo 30/minuto por IP. Generación: máximo 2/minuto por IP. Ventanas en memoria, reiniciadas al arrancar; no confiar en cabeceras de IP suministradas por el visitante. Gemini: máximo global 20 llamadas por día UTC (`GEMINI_GLOBAL_CALLS_PER_DAY`), incluidos reintentos y modelos de respaldo, mediante transacción Firestore en `publicCounters/gemini-YYYYMMDD`. Requiere `FIREBASE_PROJECT_ID`, credenciales de servidor y `GEMINI_API_KEY`. Si no se puede reservar la llamada, se devuelve plantilla (`contador_no_disponible`); cuota global agotada = `limite_global`. No se reemplaza el contador por memoria. Caché de resultados generados: 128 entradas, una hora, clave con snapshot/tema/contexto/modelos; no contiene borradores importados ni ediciones privadas. Un acierto devuelve una nueva versión `recuperado`, `usage:null` y `recoveredFromDraftId`, sin atribuir tokens de la generación original a una llamada nueva.

## Actualización de datos

`UMBRAL_SNAPSHOT_FEED_URL=https://<origen>/data/current.json`. Se comprueba al arrancar y cada 900 segundos mientras está activo. Descriptor v1:

```json
{"schemaVersion":1,"snapshotId":"YYYYMMDD-hash8","publishedAt":"2026-10-07T11:17:00Z","manifest":{"path":"snapshots/YYYYMMDD-hash8/manifest.json","sha256":"64 hex"},"files":[{"path":"snapshots/YYYYMMDD-hash8/articles.jsonl","sha256":"64 hex","sizeBytes":123}]}
```

Las rutas son relativas a la carpeta del descriptor. Se exige HTTPS, mismo origen, sin redirecciones ni rutas arbitrarias; inventario exactamente igual a `manifest.files`. Se verifican tamaños, hashes, ID de contenido, referencias de artículos/grupos/predicciones y ausencia de fixtures. El feed y `activate_snapshot` rechazan clasificadores distintos de Laya. Después se construyen los índices y se cambia una sola referencia del servicio, junto con CURRENT. Si falla, continúa el último corte válido. `/health` añade `snapshotStale` (>36 horas), `snapshotRefreshError` y `snapshotLastCheckedAt`. `Services.activate_snapshot(Path)->str` permite activar directamente un candidato local ya verificado.

## Escritorio y copia de trabajo

`UMBRAL_DESKTOP_TOKEN` habilita protección de todas las rutas `/api/v1` mediante `X-Umbral-Desktop-Token`; el proceso de escritorio crea el secreto efímero. SQLite y snapshot se configuran con `UMBRAL_SQLITE_PATH`, `UMBRAL_SNAPSHOTS_ROOT` y `UMBRAL_SNAPSHOT_DIR`. `UMBRAL_PUBLIC_API_URL` permite generación online a través de la API pública sin distribuir una clave Gemini; offline continúa la plantilla local.

Solo en `auth=local`, `localMode=true`: `GET /api/v1/workspace/export` devuelve `{format:"umbral-workspace",version:1,exportedAt:<UTC>,rules:RulesResponse,cases:[{case:CaseView,detail:TopicDetail,impactHistory:ImpactAssignment[]}]}`. `impactHistory` es opcional en copias v1 anteriores; al faltar se conserva al menos el último impacto editorial. `POST /api/v1/workspace/import` recibe ese mismo objeto y devuelve `{imported,identical}`. Casos nuevos se incorporan en una transacción, idénticos se conservan y cualquier conflicto cancela toda la importación con 409. El historial del caso debe corresponder a su versión, sin eventos saltados. Las asignaciones de impacto conservan sus justificaciones/citas y versiones consecutivas desde la primera disponible, con el último igual al impacto vigente. Los casos preservan su evidencia original después de cambiar el snapshot; las ediciones y revisión siguen usando esas citas.
