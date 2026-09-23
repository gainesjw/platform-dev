"""Execute actual template Bash against disposable packages without Azure access."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

from prepare_smoke_app import FIXTURE, prepare

ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = yaml.safe_load((ROOT / "templates/azure-functions/python/ci/stages.yml").read_text())
STEPS = TEMPLATE["stages"][0]["jobs"][0]["steps"]
VALIDATE = next(s["bash"] for s in STEPS if isinstance(s, dict)
                and s.get("displayName") == "Validate and compile deployment package")


def run_bash(script, cwd, **variables):
    env = dict(os.environ, **{key: str(value) for key, value in variables.items()})
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env["PATH"]
    return subprocess.run(["bash", "-c", script], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=60)


def test_fixture_runs_without_azure(tmp_path):
    prepare(tmp_path)
    result = subprocess.run([sys.executable, "-m", "pytest", str(FIXTURE / "smoke.py"),
                             "-q", "--override-ini=addopts="], cwd=tmp_path,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("defect", [None, "empty", "import", "syntax"])
def test_actual_package_validation_accepts_app_and_rejects_broken_packages(tmp_path, defect):
    package = tmp_path / "package"
    prepare(package)
    if defect == "empty":
        (package / "function_app.py").write_text("import azure.functions as func\napp = func.FunctionApp()\n")
    elif defect == "import":
        shutil.rmtree(package / "src")
    elif defect == "syntax":
        # Not imported: compileall must still reject it.
        (package / "broken.py").write_text("def invalid(:\n")
    result = run_bash(VALIDATE, tmp_path, PACKAGE_DIR=package)
    assert (result.returncode == 0) == (defect is None), result.stdout + result.stderr
    if defect is None:
        assert "imports and indexes successfully" in result.stdout


def test_prepare_refuses_to_overwrite_app(tmp_path):
    existing = tmp_path / "function_app.py"
    existing.write_text("existing application")
    with pytest.raises(FileExistsError):
        prepare(tmp_path)
    assert existing.read_text() == "existing application"
    assert not (tmp_path / "src").exists()


@pytest.mark.skipif(sys.platform != "linux", reason="Template uses GNU cp on Linux agents")
def test_actual_copy_step_preserves_paths_and_fails_for_missing_files(tmp_path):
    app = tmp_path / "app"
    prepare(app)
    (app / "local.settings.json").write_text('{"secret": "must not be packaged"}')
    package = tmp_path / "package"
    package.mkdir()
    copy = next(s for s in STEPS if isinstance(s, dict)
                and "${{ each path in parameters.packagePaths }}" in s)
    script = copy["${{ each path in parameters.packagePaths }}"][0]["bash"]
    paths = next(p["default"] for p in TEMPLATE["parameters"] if p["name"] == "packagePaths")
    for path in paths:
        result = run_bash(script, app, SOURCE_PATH=path, PACKAGE_DIR=package)
        assert result.returncode == 0, result.stderr
    assert (package / "src/__init__.py").is_file()
    assert (package / "function_app.py").is_file()
    assert not (package / "local.settings.json").exists()
    result = run_bash(script, app, SOURCE_PATH="missing.py", PACKAGE_DIR=package)
    assert result.returncode != 0
