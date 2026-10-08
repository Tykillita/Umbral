# PyInstaller onedir: Python, API, pipeline, ModernBERT and CPU libraries included.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

base = Path(SPECPATH)
repo = base.parents[1]
datas = []
for package in ('laya', 'transformers', 'tokenizers', 'safetensors', 'huggingface_hub', 'google_genai', 'torch', 'numpy', 'umbral_api', 'umbral_pipeline'):
    try:
        datas += copy_metadata(package.replace('_', '-'))
    except Exception:
        pass
datas += collect_data_files('laya')
datas += collect_data_files('transformers')
# TorchScript and inspection need source as well as bytecode in the frozen build.
hidden = (collect_submodules('umbral_api') + collect_submodules('umbral_pipeline')
          + collect_submodules('laya', filter=lambda name: not any(x in name for x in ('evals', 'train', 'serve', 'mcp', 'onnx')))
          + collect_submodules('transformers.models.modernbert')
          + ['transformers.models.auto.configuration_auto', 'transformers.models.auto.modeling_auto',
             'transformers.tokenization_utils_tokenizers', 'transformers.models.auto.tokenization_auto',
             'uvicorn.logging', 'uvicorn.loops.asyncio', 'uvicorn.protocols.http.h11_impl',
             'uvicorn.protocols.websockets.websockets_impl', 'uvicorn.lifespan.on', 'google.genai'])
a = Analysis([str(base / 'sidecar.py')], pathex=[str(repo / 'apps/api/src'), str(repo / 'pipeline')],
             binaries=[], datas=datas, hiddenimports=hidden,
             hookspath=[], runtime_hooks=[],
             excludes=['tensorflow', 'jax', 'matplotlib', 'scipy', 'pandas', 'IPython', 'pytest',
                       'tkinter', 'torchvision', 'torchaudio', 'laya.train', 'laya.evals',
                       'transformers.testing_utils'], noarchive=False,
             module_collection_mode={'torch': 'py', 'transformers': 'py', 'laya': 'py'})
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='umbral-sidecar',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=True,
          icon=str(repo / 'apps/web/public/brand/umbral-desktop.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='umbral-sidecar')
