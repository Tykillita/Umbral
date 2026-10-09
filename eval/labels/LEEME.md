# Cómo etiquetar (para la persona revisora)

Gracias por revisar. Su juicio es la única fuente de las métricas de clasificación, agrupación y sustento: **ni el sistema ni los agentes rellenan nada**. Si duda, escriba `no_se` o deje la fila vacía; es mejor una fila vacía que un juicio adivinado. Tiempo estimado: 45–75 minutos en total.

Hay tres hojas CSV por snapshot (el id del snapshot va en el nombre del archivo, p. ej. `clasificacion.20261007-xxxxxxxx.csv`). Ábralas con Excel o Google Sheets (UTF-8). **Solo edite las columnas `juicio_humano` y `comentario`.** No cambie `id` ni reordene filas. Guarde como CSV con el mismo nombre.

> Sesgo de anclaje: la columna `predicción` muestra lo que dijo el sistema. Para no dejarse influir, **oculte la columna C antes de empezar** y juzgue primero por el texto; si prefiere, vea la predicción solo al final para escribir un comentario.

## 1. `clasificacion.<snapshot>.csv` (hasta 150 titulares)

Solo se ve el titular (el sistema tampoco lee el artículo completo). En `juicio_humano` escriba **una** de estas etiquetas, la que mejor describe el tema principal del titular:

| Etiqueta | Cuándo usarla |
|---|---|
| `economia` | economía, inflación, empleo, inversión, finanzas, presupuesto, comercio, precios, impuestos, bancos |
| `logistica_canal` | Canal de Panamá, puertos, carga, buques, logística, cadena de suministro, zonas francas |
| `turismo` | turismo, hoteles, visitantes, aerolíneas, cruceros, destinos |
| `servicios_publicos` | agua, electricidad, salud pública, educación, transporte público, infraestructura del Estado |
| `eventos_naturales` | sismos, lluvias, inundaciones, huracanes, sequías, deslizamientos |
| `regulacion` | leyes, decretos, normas, reformas, resoluciones de entes reguladores, fallos sobre normas |
| `indeterminado` | **ninguno de los seis**: sucesos policiales/crímenes, deportes, farándula, política internacional, curiosidades, comunicados de marca, etc. |

Si un titular encaja en dos temas, elija el principal y mencione el otro en `comentario`. Los titulares no españoles se etiquetan igual (por su tema).

## 2. `pares.<snapshot>.csv` (hasta 64 pares)

Cada fila muestra dos titulares (A y B, con su medio). Pregunta: **¿informan sobre el mismo hecho o evento concreto?** (no basta con el mismo tema general). Escriba `si`, `no` o `no_se`.

- Dos medios que repiten el mismo texto (copia de agencia) siguen siendo «el mismo evento» (`si`); la cuestión de si son fuentes *independientes* se mide aparte.
- Una actualización posterior del mismo hecho (p. ej. «detienen a X» y «audiencia de X») cuenta como `si` solo si es el mismo suceso; si son fases distintas, `no`, y lo explica en `comentario`.

## 3. `afirmaciones.<snapshot>.csv` (hasta 32 afirmaciones)

Son frases generadas por el prototipo (borrador de plantilla) con su cita `[cita: id/campo]`. Para cada una, abra el titular citado (el texto de la cita es el titular en `articles.jsonl` del snapshot, o la URL en `noticias.csv`) y escriba:

| Valor | Significa |
|---|---|
| `respaldada` | el titular citado dice lo que la afirmación dice (sin añadir datos) |
| `no_respaldada` | la afirmación dice algo que el titular citado no dice (o lo contradice) |
| `cita_incorrecta` | la afirmación es razonable, pero la cita apunta a otra noticia/campo |

Recuerde: un titular solo respalda que **un medio reportó** algo; no confirma el hecho de forma independiente.

## Después de etiquetar

1. Guarde los CSV en esta carpeta (`eval/labels/`).
2. Ejecute (desde la raíz del repo): `pipeline/.venv/Scripts/python.exe eval/make_label_sheets.py import --snapshot data/snapshots/<id> --labeler "Su nombre"`. Genera `cls_labels.<id>.jsonl`, `pairs_labels.<id>.jsonl` y `claims_labels.<id>.jsonl` solo con las filas que usted juzgó.
3. Métricas (sin inventar nada):
   - `eval/run_classification.py --labels eval/labels/cls_labels.<id>.jsonl --snapshot laya=data/snapshots/<id> --out eval/results/classification-human-<id>.json`
   - `eval/run_clustering_eval.py --labels eval/labels/pairs_labels.<id>.jsonl --snapshot laya=data/snapshots/<id> --out eval/results/clustering-human-<id>.json`
   - El sustento de afirmaciones se calcula contando `respaldada` sobre las juzgadas (numerador y denominador).

## Qué muestra cada hoja y sus límites

- **Titulares:** 40 uniformes (20 TVN + 20 GDELT, uniforme *dentro* de cada fuente, no proporcional al corpus) + muestras estratificadas por categoría predicha × fuente (cada categoría: hasta 6 de TVN y 9 de GDELT; `indeterminado`: hasta 10 + 10), un titular por grupo. Resultado: las métricas son **exploratorias**, un solo revisor, y la macro-F1 estará sesgada hacia las categorías sobremuestreadas; se reporta con n y soporte por clase.
- **Pares:** priorizan grupos con ≥2 procedencias independientes, candidatos ambiguos no unidos, copias agrupadas con una sola procedencia y algunos negativos de control. El recall se mide **solo sobre pares candidatos**, no sobre todos los pares posibles.
- **Afirmaciones:** hasta 32, una por tema primero (para variar). Las 20 consultas reservadas del benchmark viven fuera del repo y no aparecen en estas hojas.
- Un solo revisor no permite medir acuerdo entre personas; si hay un segundo revisor, que etiquete una copia de las hojas por separado.
- Los archivos `*.jsonl` de muestras (`cls_sample.<id>.jsonl`, `pairs_sample.<id>.jsonl`, `claims_review.<id>.jsonl`) son la misma muestra en formato máquina; no los edite.
- Las hojas antiguas (`cls_sample.jsonl`, `pairs_sample.jsonl`, `claims_sample.jsonl`) pertenecen al snapshot `20261007-37263360` y se conservan sin tocar.

## Mismas muestras en otro corte de clasificación

Si los bytes de artículos e indicadores son idénticos entre dos snapshots verificados, `eval/rebind_label_sheets.py --source data/snapshots/<origen> --target data/snapshots/<destino>` conserva los IDs, textos, citas, comentarios y juicios de las muestras. Verifica además cada pasaje y pertenencia de las citas a sus temas; falla si cambió la evidencia o ya existe una hoja destino. Las predicciones ocultas se actualizan al destino y cada muestra registra el snapshot y hash de origen. `sheets.<destino>.meta.json` deja el recibo de integridad; no acredita una revisión humana adicional ni genera métricas.

Las hojas de `20261007-e704e952` reutilizan las 120 noticias, 50 pares y 32 afirmaciones revisables de `20261007-cfa338b6` mediante este procedimiento. Los juicios permanecen pendientes. Los 37 registros de `claims_sample` son el conjunto original de afirmaciones de plantilla del que se tomaron las 32 de `claims_review`.
