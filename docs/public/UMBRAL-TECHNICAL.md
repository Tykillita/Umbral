# Umbral | documentación técnica

> **De la señal a la decisión** · arquitectura, evidencia y límites del sistema para el jurado.

Umbral convierte señales informativas e indicadores públicos en una agenda explicable para una mesa editorial. El sistema conserva la procedencia de los datos, distingue prioridad de evidencia y entrega borradores que una persona puede revisar. No determina qué es verdadero ni publica contenido.

## En una mirada

| Decisión de diseño | Cómo se expresa en Umbral |
|---|---|
| El orden debe poder discutirse | Cada tema muestra un puntaje desglosado y una regla de priorización versionada. |
| El origen importa tanto como el texto | Las noticias se agrupan por evento y procedencia; las réplicas no cuentan como confirmaciones independientes. |
| Una cita debe poder rastrearse | Las respuestas usan identificadores y campos del corte de datos cargado. |
| La última palabra pertenece a la redacción | La generación produce borradores; revisión y publicación siguen bajo control humano. |
| Los espacios de trabajo son privados | La web guarda notas y borradores en el navegador; la API pública no conserva el trabajo editorial personal. |

## Mapa técnico

```text
TVN RSS · GDELT · Banco Mundial · USGS
                    │
                    ▼
         Ingesta y preparación de datos
   normalizar · validar · agrupar · clasificar
                    │
                    ▼
       Snapshot versionado con manifest SHA-256
                    │
                    ▼
      API FastAPI ───────────────┐
          │                      │
          ▼                      ▼
 Web Astro + React       Aplicación Windows
 navegador + IndexedDB   Electron + SQLite
          │
          ▼
 Recuperación de evidencia → borrador citado → revisión humana
```

La redacción asistida es una ruta opcional. Si el proveedor de texto no está disponible, Umbral conserva una salida basada en plantilla y evidencia recuperada.

### Componentes

| Capa | Tecnología | Función |
|---|---|---|
| Preparación | Python 3.12, `uv`, pipeline propio | Normaliza metadatos, valida registros, agrupa eventos, clasifica y empaqueta cortes reproducibles. |
| Clasificación | Laya multilingüe en PyTorch CPU | Propone categorías y señales geográficas durante la preparación de datos o en Windows. |
| Recuperación | BM25 y RapidFuzz | Busca titulares y candidatos relacionados con un tema o consulta. |
| Servicio | FastAPI, Pydantic 2 y OpenAPI | Expone agenda, fichas, consultas, borradores, revisiones y exportación. |
| Web | Astro 7, React 19, TypeScript y Tailwind 4 | Presenta la experiencia editorial en español como sitio estático. |
| Escritorio | Electron, API y pipeline empaquetados, SQLite | Permite usar Umbral en Windows con los recursos locales disponibles. |
| Generación opcional | Gemini en nivel gratuito o plantilla | Sugiere texto estructurado; la salida siempre es un borrador y conserva referencias. |

## Del origen a una ficha

El pipeline transforma entradas en un paquete de datos identificado. Conserva titulares, enlaces, medio, fechas y metadatos; no redistribuye el cuerpo de los artículos. Un indicador estadístico conserva país, serie, período y unidad para no mezclar magnitudes distintas.

| Origen | Aporte | Límite que conserva el producto |
|---|---|---|
| TVN RSS | Titular, enlace y fecha de publicación | Un titular atribuido a un medio no sustituye la nota ni una fuente primaria. |
| GDELT DOC 2.0 | Metadatos y dominios enlazados | Detectar una página no equivale a verificar lo que afirma. |
| Banco Mundial | Series oficiales de contexto | Un dato anual identifica su año y unidad; no confirma automáticamente una cifra trimestral. |
| USGS | Catálogo de eventos sísmicos | Su cobertura regional no equivale a una medición de impacto en Panamá. |

Cada snapshot contiene registros normalizados, reporte de calidad y un manifest con huellas SHA-256. Las marcas de tiempo se guardan en UTC; la interfaz las presenta en hora de Panamá. Al cargar un corte, la API comprueba su integridad y mantiene sus predicciones asociadas a la versión correspondiente.

### Corte usado en los ejemplos

Los casos y mediciones incluidos en este dossier corresponden al snapshot `20261007-cfa338b6`, creado el 7 de octubre de 2026 a las 13:34:20 UTC. El manifest registra 991 noticias válidas (122 de TVN y 869 de GDELT), 80 registros inválidos apartados, 540 valores de indicadores, 910 grupos y 991 predicciones; el corte no contiene fixtures. Su SHA-256 es `DBBA62F3D01D962D09018F7A00B82E6FD068AA7B705145898A9B2C739A74B050`.

Este es el corte reproducible de referencia para los ejemplos de esta entrega. Fue descrito como provisional: no se contaba con un paquete oficial congelado y algunas consultas a GDELT recibieron HTTP 429. Las cifras sirven para explicar ese corte, no para describir una agenda en vivo ni para afirmar que el feed actual tenga los mismos datos.

## Priorización: orden de lectura, no veredicto

La regla `scoring-v1` asigna un puntaje de 0 a 100:

**P = 30R + 25I + 20U + 15N + 10E**

| Variable | Señal que representa |
|---|---|
| R | Relevancia para Panamá |
| I | Impacto editorial propuesto y su justificación |
| U | Urgencia respecto de la fecha original |
| N | Novedad del evento; la recirculación no añade novedad |
| E | Solidez de procedencia, independencia y relación con fuentes primarias |

Las bandas son bajo `[0, 40)`, medio `[40, 70)` y alto `[70, 100]`. El puntaje ordena qué abrir primero. El **estado de evidencia** —insuficiente, parcial o suficiente para elaborar un borrador— responde una pregunta distinta. Un asunto prioritario puede seguir requiriendo investigación. Las probabilidades del clasificador del corte de referencia no están calibradas.

## API y productos

La API ofrece contratos tipados y documentados. Entre sus operaciones públicas están:

| Operación | Ruta |
|---|---|
| Salud, versión y snapshot | `GET /api/v1/health` |
| Agenda y detalle de tema | `GET /api/v1/topics` · `GET /api/v1/topics/{id}` |
| Consulta con evidencia | `POST /api/v1/queries` |
| Borrador asociado a un tema | `POST /api/v1/topics/{id}/drafts` |
| Revisión editorial | `PATCH /api/v1/cases/{id}/review` |
| Exportar ficha | `GET /api/v1/cases/{id}/export` |

La versión web pública no requiere cuenta. El trabajo personal vive en IndexedDB en ese navegador y se puede exportar o restaurar como paquete JSON; la API pública no guarda ese espacio. La aplicación de Windows utiliza SQLite bajo el perfil del usuario y puede trabajar sin red si dispone del corpus y del modelo locales. Gemini y la captura de fuentes nuevas requieren conectividad.

## Citas, generación y manejo seguro

Antes de mostrar una respuesta generada, Umbral valida que las referencias existan, pertenezcan al snapshot correcto y respeten el esquema esperado. Las propuestas pueden contener un brief, enfoque, preguntas, verificaciones, guion breve y copy. La interfaz identifica si el texto fue generado por un modelo, recuperado o armado con plantilla.

La comprobación estructural confirma que una referencia se puede localizar; no certifica que la frase represente fielmente la fuente. Esa lectura corresponde a la persona editora. El contenido externo se trata como dato no confiable, nunca como una instrucción del sistema. Aprobar una revisión conserva un borrador y no activa publicación.

## Evidencia de desarrollo

Estas mediciones describen pruebas programáticas y muestras de desarrollo, no resultados de una redacción ni una evaluación humana de exactitud.

| Medición | Resultado registrado | Lectura adecuada |
|---|---|---|
| Consultas locales de desarrollo, 40 preguntas sobre `cfa338b6` | 20/20 respuestas respondibles incluyeron una cita; 14/14 abstenciones correctas; 0/20 abstenciones incorrectas; 7/7 sondas adversariales; 0 errores HTTP | La presencia de citas y las reglas de abstención se pueden medir; no equivalen a una revisión del sustento de cada afirmación. |
| Recuperación local caliente | Mediana de 0,056 s | No incluye red, Gemini ni arranque de un servicio remoto. |
| Generación opcional con Gemini, 10 casos | 8/10 pasaron validación estructural; en 2/10 se conservó el fallback tras timeout | Muestra pequeña; la estructura no demuestra fidelidad factual. |

El benchmark local se registró el 7 de octubre de 2026 a las 13:34:56 UTC. El artefacto de resultados tiene SHA-256 `5261BDAED2FA030DFB9B7540187A64FC1043F136515C3C0F251D0965D08926BA`. La muestra de Gemini se registró el 8 de octubre de 2026 a las 06:20:28 UTC; su artefacto tiene SHA-256 `70B6CC150E3313DAA4264C30392A14374A33FFBCB3209D84E4D22927414776D0`.

## Límites y responsabilidad

- Umbral trabaja principalmente con titulares y metadatos, no con el texto completo de cada artículo.
- La clasificación, el puntaje y una cita válida no son veredictos de verdad.
- Las fuentes repetidas no suman corroboración cuando comparten procedencia.
- No se han medido ahorro de tiempo, mejora de audiencia ni impacto comercial.
- Ninguna salida reemplaza la lectura de fuentes ni el criterio editorial humano.
- Umbral no publica noticias ni alertas automáticamente.

La visión funcional y la narrativa de demo están en [Documentación funcional](./UMBRAL-FUNCTIONAL.md) y [Pitch Day](./UMBRAL-PITCH-DAY.md). La descripción general del proyecto está en el [README en español](../../README.es.md).
