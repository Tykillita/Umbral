from pathlib import Path

import yaml


def test_daily_workflow_runs_the_current_hosted_verifier():
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.load(
        (root / ".github" / "workflows" / "daily-data.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    steps = workflow["jobs"]["refresh"]["steps"]
    tools = next(
        step for step in steps
        if step.get("name") == "Traer las herramientas actuales desde el commit de este workflow"
    )
    verifier = next(step for step in steps if step.get("name") == "Verificar el feed alojado y conservar el recibo")

    assert tools["with"]["ref"] == "${{ github.sha }}"
    assert "scripts/verify_hosted.py" in tools["with"]["sparse-checkout"].splitlines()
    assert "python .workflow-tools/scripts/verify_hosted.py" in verifier["run"]
