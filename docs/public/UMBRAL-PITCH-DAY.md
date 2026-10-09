# Pitch Day | Umbral

> **De la señal a la decisión** · narrativa de presentación, demo de 10 minutos y conversación con el jurado.

## La idea en una frase

Umbral convierte señales de noticias en una agenda editorial explicable: muestra qué conviene revisar, de dónde viene cada afirmación y dónde termina la evidencia disponible.

**Frase de cierre:** Una agenda útil no solo ordena temas; deja a la vista por qué los ordenó así.

## Estructura para diez minutos

| Tiempo | Pantalla o acción | Mensaje para el jurado |
|---|---|---|
| 0:00–1:00 | Portada y problema | Una mesa recibe muchas señales; necesita decidir cuáles abrir y con qué respaldo. |
| 1:00–2:00 | Agenda | El puntaje ordena la atención. El estado de evidencia explica cuánto se puede sostener. |
| 2:00–2:45 | Mapa del flujo | Fuentes públicas, preparación reproducible, snapshot identificado y una interfaz para revisar. |
| 2:45–3:35 | Caso presupuestario | Alta prioridad puede convivir con evidencia insuficiente. El orden no certifica la noticia. |
| 3:35–4:25 | Caso del PIB | Un dato anual de 2024 da contexto a un titular trimestral de 2026; no lo confirma. |
| 4:25–5:30 | Borrador y citas | La salida conserva su origen y sus referencias. La revisión sigue en manos de la persona. |
| 5:30–7:10 | Consulta y mediciones | Mostrar cómo Umbral cita o se abstiene y presentar los resultados programáticos con su alcance. |
| 7:10–8:30 | Web, escritorio y privacidad | Explicar dónde vive el trabajo personal y qué requiere conexión. |
| 8:30–10:00 | Cierre en la agenda | Umbral devuelve una primera lectura trazable; el equipo conserva el criterio y la decisión. |

## Guion hablado

### 0:00–1:00 · El trabajo empieza antes de escribir

“En una mesa editorial, el primer reto no siempre es redactar. Es decidir cuál de muchas señales merece atención, cuáles repiten la misma procedencia y qué información realmente sostiene una afirmación. Umbral organiza esa primera lectura y hace visible su recorrido.”

### 1:00–2:00 · Una agenda que explica su orden

“La agenda usa cinco componentes visibles: relevancia, impacto, urgencia, novedad y evidencia. El puntaje sugiere por dónde empezar; el estado de evidencia indica cuánto respalda el material disponible. Son dos lecturas distintas. Una historia puede quedar arriba de la lista y aun así requerir más investigación.”

### 2:00–2:45 · Cómo llega la señal a la mesa

“Umbral recoge metadatos de noticias e indicadores oficiales, normaliza y agrupa los registros, conserva un corte identificable y prepara fichas para revisión. Así podemos hablar del dato que alimentó una pantalla y distinguir lo que el sistema organiza de lo que una persona debe juzgar.”

### 2:45–4:25 · Dos ejemplos, dos límites

“En este caso presupuestario, el tema obtiene 74,55 puntos, pero el respaldo es insuficiente porque solo vemos una procedencia. La prioridad lo pone a la vista; no certifica el contenido.

“En el caso económico, el titular habla de crecimiento trimestral de 2026. El Banco Mundial aporta una serie anual de 2024. Umbral conserva año y unidad para mostrar que ese indicador sirve como contexto, pero no confirma la cifra trimestral.”

### 4:25–5:30 · Un borrador que conserva sus referencias

“Desde una ficha podemos preparar un brief, preguntas, verificaciones y un guion. La interfaz identifica el origen del texto y mantiene citas al corte de datos. Si el material no alcanza para una respuesta, Umbral puede abstenerse. La persona edita, registra su revisión y conserva la responsabilidad.”

### 5:30–7:10 · Qué medimos y qué significa

“En una exploración local de 40 preguntas de desarrollo sobre un corte específico, veinte preguntas respondibles recibieron respuestas con al menos una cita; las catorce situaciones diseñadas para abstenerse lo hicieron correctamente; siete sondas adversariales pasaron sus reglas y no hubo errores HTTP. La recuperación local caliente tuvo una mediana de 0,056 segundos. Son resultados programáticos: no demuestran que cada cita sostenga una frase ni que una redacción trabaje mejor.”

### 7:10–8:30 · Una herramienta para el equipo, no un archivo personal

“La web guarda borradores y notas en el navegador de quien la usa; la API pública no conserva ese espacio personal. La aplicación de Windows puede utilizar SQLite y trabajar con el corpus y modelo locales. La consulta de fuentes nuevas y Gemini necesitan conexión. No hay una publicación automática ni una cuenta editorial central.”

### 8:30–10:00 · Cierre

“Umbral no decide qué se publica ni etiqueta una noticia como verdadera o falsa. Hace más clara la primera decisión: qué mirar, por qué mirarlo y qué falta para sostenerlo. La mesa recibe una agenda trazable y conserva la última palabra.”

## Evidencia que se puede mostrar

Todas las cifras siguientes describen experimentos de desarrollo registrados sobre `20261007-cfa338b6`; no representan una evaluación humana de utilidad editorial.

| Lectura | Resultado | Alcance |
|---|---|---|
| Benchmark de consultas | 20/20 respuestas con alguna cita; 14/14 abstenciones correctas; 0/20 abstenciones incorrectas en preguntas respondibles; 7/7 sondas adversariales; 0 errores HTTP | 40 preguntas redactadas para desarrollo. La presencia de una cita no certifica que el texto esté bien sustentado. |
| Recuperación local | Mediana de 0,056 s | API local en caliente; no incluye Gemini, red ni arranque remoto. |
| Muestra con Gemini | 8/10 salidas aceptadas por validación estructural; 2/10 conservaron el fallback tras un timeout | Muestra pequeña; la validación estructural no equivale a revisión factual humana. |

El benchmark quedó registrado el 7 de octubre de 2026 a las 13:34:56 UTC. La muestra con Gemini quedó registrada el 8 de octubre a las 06:20:28 UTC. En la demo, muestra el identificador del snapshot visible en la aplicación cuando cites un caso o una métrica.

## Preguntas que puede hacer el jurado

### ¿El puntaje dice si una noticia es verdadera?

No. Ordena señales con cinco componentes para ayudar a decidir qué revisar. No es probabilidad de verdad ni una autorización para publicar.

### ¿Dos medios cuentan como dos fuentes?

Solo si tienen procedencias independientes. La repetición de un mismo cable no multiplica la corroboración.

### ¿Qué demuestra una cita?

Que la referencia se puede localizar en el corte y que apunta a un elemento del esquema esperado. La persona editora todavía debe comprobar si la frase representa correctamente la fuente.

### ¿Qué significa 20 de 20?

Que en esas veinte respuestas la API incluyó al menos una cita. No dice que cada afirmación sea cierta ni mide la calidad editorial de una agenda.

### ¿Umbral puede publicar una noticia?

No. La aprobación conserva el borrador para la siguiente decisión humana; no lo envía a una audiencia.

### ¿Se ha medido cuánto tiempo ahorra?

No. La evaluación descrita mide reglas y comportamiento del prototipo en pruebas de desarrollo. Ahorro de tiempo, impacto de audiencia y mejora editorial requieren una evaluación en una redacción.

### ¿Funciona sin conexión?

La aplicación de Windows puede trabajar localmente con el modelo y el corpus disponibles. Gemini y la captura de fuentes nuevas requieren internet.

## Tres ideas para dejar en la sala

1. **Ordenar no es certificar.** El puntaje ayuda a decidir qué revisar primero.
2. **Contexto no es confirmación.** Cada fuente e indicador conserva su origen, fecha y unidad.
3. **La decisión se queda con el equipo.** Umbral prepara señales y borradores; la redacción decide qué hacer con ellos.

Consulta la [documentación técnica](./UMBRAL-TECHNICAL.md) y la [experiencia funcional](./UMBRAL-FUNCTIONAL.md) para ampliar el recorrido.
