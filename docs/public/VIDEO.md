# Recorrido audiovisual de Umbral

La presentación dura 77 segundos y recorre Agenda, Ficha, Asistente, Borradores, revisión, exportación Markdown y Fuentes. Las pantallas son capturas de `/app`, con el snapshot real provisional `20261007-e704e952`; los manifiestos en `docs/video/captures` identifican el commit, caso, clics y hashes de cada toma. El trabajo editorial se creó en SQLite desechable, en modo offline, sin fixtures ni solicitudes externas.

| Edición | Resolución | Archivo |
|---|---|---|
| Recorrido en español | 1920 × 1080 | [MP4](../video/umbral-tour-es.mp4) |
| Recorrido en inglés | 1920 × 1080 | [MP4](../video/umbral-tour-en.mp4) |
| Reel en español | 1080 × 1920 | [MP4](../video/umbral-reel-es.mp4) |
| Reel en inglés | 1080 × 1920 | [MP4](../video/umbral-reel-en.mp4) |

Los cuatro MP4 usan H.264, AAC y 30 fps. La interfaz conserva su idioma español; la edición inglesa traduce narración, cartelas y subtítulos. Los subtítulos están incrustados en la imagen y se ofrecen también como WebVTT: [español](../video/umbral-es.vtt) · [inglés](../video/umbral-en.vtt). Las voces locales son Microsoft Helena Desktop (es-ES) y Zira Desktop (en-US).

La narración identifica el borrador mostrado como plantilla offline y conserva el alcance de la evidencia: prioridad alta puede coexistir con evidencia insuficiente, los titulares no sustituyen al artículo completo y aprobar un borrador no publica una noticia. Las revisiones y ediciones del video son de demostración.

## Fuentes y reproducción

El guion y los tiempos viven en [storyboard.json](../video/storyboard.json). [capture.py](../video/capture.py) registra acciones reales con cursor y ondas visibles; [render.py](../video/render.py) monta las capturas, anima las cartelas y sincroniza voz, clics y subtítulos. La voz se sintetiza por frase para que cada cue de subtítulo tenga la duración de su audio, conservando la misma narración entre orientaciones.

La música es la pista original de [isTargetSleeping](https://github.com/Tykillita/isTargetSleeping), proyecto MIT del mismo autor, conservada en `docs/video/source-music.m4a`. Los sonidos adicionales de ratón se sintetizan a partir de los eventos de clic capturados. Barlow Condensed y Atkinson Hyperlegible mantienen sus licencias OFL en `docs/video/fonts`.

Se requieren Windows con ambas voces instaladas, FFmpeg/FFprobe en PATH, Node 24, `uv` y las dependencias de Umbral. Las herramientas de medios se instalan dentro del proyecto:

```powershell
uv venv .production/video-work/venv --python 3.12
uv pip install --python .production/video-work/venv/Scripts/python.exe pillow==12.3.0 numpy==2.5.3 fonttools==4.66.1 playwright==1.63.0
.production/video-work/venv/Scripts/python.exe -m playwright install chromium

cd apps/web
$env:PUBLIC_API_MODE='live'; $env:PUBLIC_API_URL=''; $env:PUBLIC_AUTH_MODE='local'
$env:ASTRO_TELEMETRY_DISABLED='1'
./node_modules/node/node_modules/node-win-x64/bin/node.exe node_modules/astro/bin/astro.mjs build
cd ../..
```

Para renovar las tomas, abre dos terminales: `docs/video/serve.ps1 -Port 8876` y `docs/video/serve.ps1 -Port 8877`. Cada arranque crea una base SQLite nueva. Desde una tercera terminal:

```powershell
.production/video-work/venv/Scripts/python.exe docs/video/capture.py --format landscape --base http://127.0.0.1:8876
.production/video-work/venv/Scripts/python.exe docs/video/capture.py --format portrait --base http://127.0.0.1:8877
.production/video-work/venv/Scripts/python.exe docs/video/render.py --prepare --format landscape
.production/video-work/venv/Scripts/python.exe docs/video/render.py --prepare --format portrait
```

Las capturas normalizadas incluidas permiten volver a montar el video sin renovar las tomas. Genera la voz, revisa fotogramas y exporta:

```powershell
docs/video/speech.ps1
.production/video-work/venv/Scripts/python.exe docs/video/render.py --prepare-audio
foreach ($language in @('es','en')) {
    foreach ($orientation in @('landscape','portrait')) {
        .production/video-work/venv/Scripts/python.exe docs/video/render.py --stills --lang $language --format $orientation
    }
}
# Revisa .production/video-work/review antes de exportar.
foreach ($language in @('es','en')) {
    foreach ($orientation in @('landscape','portrait')) {
        .production/video-work/venv/Scripts/python.exe docs/video/render.py --lang $language --format $orientation
    }
}
.production/video-work/venv/Scripts/python.exe docs/video/verify.py
```

[verification.json](../video/verification.json) guarda la ejecución real del verificador, con fecha UTC, hashes, duración, fotogramas, resolución, audio y procedencia de las capturas. La revisión de imágenes y el verificador cubren el medio; no constituyen evaluación humana de la calidad editorial del producto.

Los reproductores de los README usan adjuntos de GitHub. Para sustituir una edición, sube su MP4 terminado sin recomprimirlo y actualiza su URL `github.com/user-attachments/assets/…` en el README correspondiente. Conserva las ediciones descargables del repositorio y los subtítulos equivalentes.
