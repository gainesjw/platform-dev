"""Execute the CD template's real verification script with mocked DevOps responses."""
import io
import json
from pathlib import Path
from unittest.mock import MagicMock
import urllib.error
import urllib.request

import pytest
import yaml

STEP = yaml.safe_load((Path(__file__).resolve().parents[3] /
    "templates/azure-functions/python/cd/verify-ci-run.yml").read_text())["steps"][0]
SCRIPT = STEP["bash"].split("python - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]


@pytest.fixture
def build_response(monkeypatch):
    variables = {
        "CI_RUN_ID": "42", "CI_PIPELINE_ID": "7", "COLLECTION_URI": "https://dev.azure.com/example/",
        "PROJECT_ID": "project-id", "SYSTEM_ACCESSTOKEN": "private-token",
        "DEPLOYMENT_BRANCH": "refs/heads/main", "APP_REPOSITORY_ID": "app-repo",
        "APP_SOURCE_VERSION": "tested-commit",
    }
    for key, value in variables.items():
        monkeypatch.setenv(key, value)
    return {"status": "completed", "result": "succeeded", "reason": "individualCI",
            "definition": {"id": 7}, "repository": {"id": "app-repo"},
            "sourceVersion": "tested-commit", "sourceBranch": "refs/heads/main"}


def run_script(monkeypatch, build):
    fetch = MagicMock(return_value=io.StringIO(json.dumps(build)))
    monkeypatch.setattr(urllib.request, "urlopen", fetch)
    exec(compile(SCRIPT, "verify-ci-run.yml", "exec"), {})
    return fetch


def test_accepts_exact_successful_ci_run(monkeypatch, build_response, capsys):
    fetch = run_script(monkeypatch, build_response)
    request = fetch.call_args.args[0]
    assert request.full_url.endswith("/project-id/_apis/build/builds/42?api-version=7.1")
    assert request.get_header("Authorization") == "Bearer private-token"
    assert "private-token" not in capsys.readouterr().out


@pytest.mark.parametrize("field,value,message", [
    ("status", "inProgress", "completed, successful"),
    ("result", "failed", "completed, successful"),
    ("result", "partiallySucceeded", "completed, successful"),
    ("result", "canceled", "completed, successful"),
    ("definition", {"id": 8}, "configured CI pipeline"),
    ("reason", "pullRequest", "PR builds"),
    ("sourceBranch", "refs/heads/feature", "deployment branch"),
    ("repository", {"id": "different-app"}, "same application repository"),
    ("sourceVersion", "different-commit", "differs from CI commit"),
])
def test_rejects_unfit_artifact(monkeypatch, build_response, field, value, message):
    build_response[field] = value
    with pytest.raises(RuntimeError, match=message):
        run_script(monkeypatch, build_response)


def test_api_denial_fails_closed(monkeypatch, build_response):
    monkeypatch.setattr(urllib.request, "urlopen", MagicMock(side_effect=
        urllib.error.HTTPError("https://dev.azure.com/example", 403, "Forbidden", {}, None)))
    with pytest.raises(urllib.error.HTTPError):
        exec(compile(SCRIPT, "verify-ci-run.yml", "exec"), {})
