from pathlib import Path

import pytest
from prepare_laya_production_model import _require_runtime_layout


def test_laya_production_artifact_requires_the_files_used_by_the_loader(tmp_path: Path):
    with pytest.raises(ValueError, match=r"rl_agent_config\.json, tokenizer[\\/]+tokenizer\.json, encoder[\\/]+config\.json"):
        _require_runtime_layout(tmp_path)


def test_laya_production_artifact_accepts_a_complete_runtime_layout(tmp_path: Path):
    for relative in ("rl_agent_config.json", "tokenizer/tokenizer.json", "encoder/config.json"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    _require_runtime_layout(tmp_path)
