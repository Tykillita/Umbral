# Umbral | documentación funcional

> **Una agenda para decidir dónde mirar primero** · recorrido de la experiencia editorial para el jurado.

## El reto de la mesa

Una redacción recibe titulares con fechas, coberturas y grados de respaldo distintos. El volumen por sí solo no resuelve tres preguntas: qué vale la pena abrir primero, qué puede sostenerse con las fuentes disponibles y qué conviene conseguir antes de redactar.

Umbral convierte esa primera lectura en un recorrido visible. Agrupa señales relacionadas, muestra sus procedencias, ordena temas con criterios explícitos y permite preparar borradores citados. El equipo mantiene el contexto, la revisión y la responsabilidad de publicar.

## Para quién está pensado

| Persona | Qué necesita resolver |
|---|---|
| Editor/a de mesa | Comparar asuntos y decidir cuál merece asignación. |
| Periodista | Seguir una afirmación hasta el titular, la fuente y el dato que la originó. |
| Productor/a digital o audiovisual | Adaptar un primer borrador a brief, preguntas, guion o copy. |
| Persona revisora | Dejar constancia de su criterio, conservar versiones y exportar una ficha de trabajo. |

La interfaz está en español. Las propuestas del sistema aparecen como borradores y no atribuyen la autoría editorial a una máquina.

## Dos lecturas que se complementan

| En pantalla | Pregunta | Uso práctico |
|---|---|---|
| Puntaje de prioridad | ¿Qué tema conviene mirar primero? | Ordena señales con relevancia, impacto, urgencia, novedad y evidencia. |
| Estado de evidencia | ¿Qué permite afirmar el material disponible? | Expone si el respaldo es insuficiente, parcial o suficiente para un borrador. |

No se deben confundir: un puntaje alto puede señalar una historia que requiere más investigación. Si varios medios reproducen un mismo cable, Umbral los presenta como una misma procedencia y evita inflar la corroboración.

## Recorrido editorial

### 1. Elegir una señal en la agenda

La agenda presenta temas ordenados, filtros y una explicación de los componentes del puntaje. La mesa puede comparar por fecha, categoría, medio y estado de evidencia antes de abrir una ficha.

**La pantalla facilita:** decidir qué revisar primero. **La pantalla no decide:** qué debe cubrir la redacción.

### 2. Entender qué hay detrás

La ficha reúne titulares relacionados, sus medios y fechas, procedencias, indicadores oficiales, discrepancias y preguntas que requieren confirmación. Las fechas de publicación y captura aparecen separadas del período al que se refiere una estadística. Si el material disponible es solo un titular y metadatos, la ficha lo señala.

### 3. Preguntar al corpus

El asistente busca en el corte de datos identificado y devuelve referencias a los elementos recuperados. Un indicador conserva su país, año y unidad. Cuando el corpus no sostiene una respuesta, Umbral puede abstenerse y explicar qué tipo de evidencia ayudaría.

### 4. Preparar una pieza inicial

La persona puede trabajar un brief, un título, un enfoque, preguntas de investigación, verificaciones, un guion breve y un copy. Las afirmaciones recuperadas conservan referencias al corte. La interfaz indica si el borrador viene de un modelo, de una recuperación anterior o de una plantilla.

El texto se mantiene acotado a la evidencia disponible. Si la fuente no sostiene más detalle, el sistema no rellena el espacio con hechos inventados.

### 5. Revisar y conservar criterio

La persona responsable registra su nombre, estado y comentario. El historial conserva las versiones y actividad del caso. Aprobar significa que el borrador está listo para la siguiente decisión editorial; no equivale a publicarlo.

### 6. Guardar o compartir el trabajo

En web, las notas, revisiones y versiones se guardan en el navegador. Se pueden exportar o restaurar en un paquete JSON y exportar fichas a Markdown. La aplicación Windows utiliza almacenamiento local SQLite. La API pública no convierte el espacio editorial personal en un archivo central.

## Cuatro escenas del corte de demostración

Los ejemplos pertenecen al snapshot `20261007-cfa338b6`. Sus puntuaciones describen ese corte y no son una recomendación en vivo ni un dictamen sobre la verdad de una noticia.

| Escena | Lo que enseña la experiencia |
|---|---|
| Tránsitos del Canal | Dos procedencias distintas elevan el respaldo relativo; el caso marca 76,7 puntos y evidencia parcial. La coincidencia aún no sustituye una fuente primaria. |
| PIB trimestral | Un titular habla de crecimiento de 6,4 % en el segundo trimestre de 2026. La serie del Banco Mundial disponible en el corte es anual y corresponde a 2024: aporta contexto, no confirma la cifra trimestral. |
| Selección cultural | Dos medios recogen el tema «Chichero» y los premios Óscar/Goya. El caso muestra que una señal puede quedar fuera de las seis categorías temáticas del corte aunque tenga interés para la conversación editorial. |
| Créditos presupuestarios | Un titular sobre traslados y créditos por cerca de 100 millones obtiene 74,55 puntos y mantiene evidencia insuficiente con una procedencia. Prioridad alta significa que vale la pena mirar; no que esté listo para publicar. |

El contraste entre estos casos hace visible la propuesta funcional: ordenar la atención sin esconder incertidumbre ni convertir contexto en confirmación.

## Promesa de producto y alcance

| Umbral ayuda a… | Umbral no… |
|---|---|
| Comparar señales con un criterio legible | Declara que una noticia sea verdadera o falsa |
| Rastrear qué fuente originó una afirmación | Trata una cita estructuralmente correcta como validación editorial |
| Encontrar contexto en indicadores oficiales | Presenta cifras de distinto año o unidad como si fueran equivalentes |
| Preparar y revisar borradores | Publica, envía alertas o toma la decisión final por la redacción |

El prototipo no utiliza datos de audiencia o rating, no produce una pieza audiovisual completa y no mide ahorro de tiempo ni mejora de resultados editoriales. Su valor demostrable es organizar señales, mostrar razones y dejar claro hasta dónde alcanza el material.

## Principios que guían la lectura

- La atribución precede a la afirmación: un titular es lo que un medio reporta.
- La repetición no equivale a una segunda fuente independiente.
- El año, país y unidad viajan junto al dato estadístico.
- Una diferencia entre cifras se formula como pregunta para investigar.
- Una fuente puede contener texto no confiable; ese texto nunca gobierna a Umbral.
- La persona editora conserva autoría, revisión y última decisión.

Lee también la [documentación técnica](./UMBRAL-TECHNICAL.md) y el [guion del Pitch Day](./UMBRAL-PITCH-DAY.md).
