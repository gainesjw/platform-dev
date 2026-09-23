"""Shared deployment checks tested without Azure access."""
from unittest.mock import MagicMock
import pytest
from platform_azure_functions import deployment as validation

@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    monkeypatch.delenv("IS_FLEX_CONSUMPTION", raising=False)

def test_validation_fails_when_output_never_arrives(monkeypatch):
    monkeypatch.setattr(validation.time, "monotonic", MagicMock(side_effect=[0, 0, 11]))
    monkeypatch.setattr(validation.time, "sleep", MagicMock())
    with pytest.raises(RuntimeError, match="Timed out"):
        validation.wait_until(lambda: False, "fresh output", timeout=10)


def test_validation_retries_until_ready(monkeypatch):
    sleep = MagicMock()
    monkeypatch.setattr(validation.time, "sleep", sleep)
    check = MagicMock(side_effect=[False, True])
    validation.wait_until(check, "host ready")
    assert check.call_count == 2
    sleep.assert_called_once_with(10)


@pytest.fixture
def preflight_responses(monkeypatch):
    for name, value in {
        "FUNCTION_APP_NAME": "test-app",
        "RESOURCE_GROUP_NAME": "test-group",
        "PYTHON_VERSION": "3.12",
        "STORAGE_ACCOUNT_NAME": "examplestorageaccount",
        "CONTAINER_NAME": "dummy-data",
    }.items():
        monkeypatch.setenv(name, value)
    return [
        {"kind": "functionapp,linux", "state": "Running",
         "identity": {"type": "SystemAssigned"}},
        {"linuxFxVersion": "PYTHON|3.12"},
        [{"name": "FUNCTIONS_WORKER_RUNTIME", "value": "python"},
         {"name": "FUNCTIONS_EXTENSION_VERSION", "value": "~4"},
         {"name": "STORAGE_ACCOUNT_NAME", "value": "examplestorageaccount"},
         {"name": "CONTAINER_NAME", "value": "dummy-data"},
         {"name": "AzureWebJobsStorage", "value": "private-test-value"}],
    ]


def mock_cli(monkeypatch, responses):
    import json
    run = MagicMock(side_effect=[
        MagicMock(returncode=0, stdout=json.dumps(response)) for response in responses
    ])
    monkeypatch.setattr(validation.subprocess, "run", run)
    return run


@pytest.mark.parametrize("nested", [False, True])
def test_preflight_accepts_cli_response_formats(monkeypatch, preflight_responses, nested, capsys):
    if nested:
        app = preflight_responses[0]
        app["properties"] = {"state": app.pop("state")}
        preflight_responses[1] = {"properties": preflight_responses[1]}
    mock_cli(monkeypatch, preflight_responses)
    validation.preflight()
    output = capsys.readouterr().out
    assert "Preflight passed" in output
    assert "private-test-value" not in output


def test_missing_state_names_the_field(monkeypatch, preflight_responses):
    del preflight_responses[0]["state"]
    mock_cli(monkeypatch, preflight_responses)
    with pytest.raises(RuntimeError, match="missing required field 'state'"):
        validation.preflight()


def test_missing_pipeline_variable_is_actionable(monkeypatch):
    monkeypatch.delenv("PYTHON_VERSION", raising=False)
    with pytest.raises(RuntimeError, match="Missing pipeline environment variable: PYTHON_VERSION"):
        validation.preflight()


def test_null_identity_gives_configuration_error(monkeypatch, preflight_responses):
    preflight_responses[0]["identity"] = None
    mock_cli(monkeypatch, preflight_responses)
    with pytest.raises(RuntimeError, match="Enable a managed identity"):
        validation.preflight(require_managed_identity=True)


def test_malformed_settings_does_not_expose_values(monkeypatch, preflight_responses):
    preflight_responses[2] = [{"value": "private-test-value"}]
    mock_cli(monkeypatch, preflight_responses)
    with pytest.raises(RuntimeError, match="entry missing 'name' or 'value'") as exc:
        validation.preflight()
    assert "private-test-value" not in str(exc.value)


def test_nested_verification_responses(monkeypatch, preflight_responses):
    mock_cli(monkeypatch, [
        {"properties": {"masterKey": "private-test-key"}},
        {"value": [{"name": "app/run_dummy_collector", "properties": {
            "config": {"bindings": [{"type": "timerTrigger", "schedule": "0 0 */4 * * *"}]}
        }}]},
    ])
    assert validation.az("keys", "list")["masterKey"] == "private-test-key"
    functions = validation.az("function", "list")
    assert functions[0]["config"]["bindings"][0]["schedule"] == "0 0 */4 * * *"


@pytest.mark.parametrize("version", ["3.14", "3.12"])
def test_flex_runtime_and_settings(monkeypatch, preflight_responses, version, capsys):
    monkeypatch.setenv("IS_FLEX_CONSUMPTION", "true")
    monkeypatch.setenv("PYTHON_VERSION", "3.14")
    app = preflight_responses[0]
    app["properties"] = {
        "state": app.pop("state"),
        "functionAppConfig": {"runtime": {"name": "python", "version": version}},
        "siteConfig": {"linuxFxVersion": ""},
    }
    run = mock_cli(monkeypatch, [app, [
        {"name": "STORAGE_ACCOUNT_NAME", "value": "examplestorageaccount"},
         {"name": "CONTAINER_NAME", "value": "dummy-data"},
         {"name": "AzureWebJobsStorage", "value": "private-test-value"},
    ]])
    if version == "3.14":
        validation.preflight()
        assert "Preflight passed" in capsys.readouterr().out
        assert run.call_count == 2  # No legacy config show or runtime app settings.
    else:
        with pytest.raises(RuntimeError, match="expected python 3.14, received python 3.12"):
            validation.preflight()


def test_flex_app_rejects_non_flex_pipeline(monkeypatch, preflight_responses):
    monkeypatch.setenv("IS_FLEX_CONSUMPTION", "false")
    preflight_responses[0]["functionAppConfig"] = {"runtime": {"name": "python", "version": "3.14"}}
    mock_cli(monkeypatch, preflight_responses)
    with pytest.raises(RuntimeError, match="configure the pipeline for Flex Consumption"):
        validation.preflight()



@pytest.mark.parametrize("required", [False, True])
def test_identity_is_an_explicit_requirement(monkeypatch, preflight_responses, required):
    preflight_responses[0]["identity"] = None
    mock_cli(monkeypatch, preflight_responses)
    if required:
        with pytest.raises(RuntimeError, match="managed identity"):
            validation.preflight(require_managed_identity=True)
    else:
        validation.preflight()


@pytest.mark.parametrize("required", [False, True])
def test_host_storage_is_an_explicit_requirement(monkeypatch, preflight_responses, required):
    preflight_responses[2] = [v for v in preflight_responses[2] if v["name"] != "AzureWebJobsStorage"]
    mock_cli(monkeypatch, preflight_responses)
    if required:
        with pytest.raises(RuntimeError, match="AzureWebJobsStorage"):
            validation.preflight(require_host_storage=True)
    else:
        validation.preflight()


def test_preflight_does_not_require_collector_destination(monkeypatch, preflight_responses):
    monkeypatch.delenv("STORAGE_ACCOUNT_NAME", raising=False)
    monkeypatch.delenv("CONTAINER_NAME", raising=False)
    preflight_responses[2] = [v for v in preflight_responses[2] if v["name"] not in ("STORAGE_ACCOUNT_NAME", "CONTAINER_NAME")]
    mock_cli(monkeypatch, preflight_responses)
    validation.preflight()


@pytest.mark.parametrize("success", [True, False])
def test_cli_setting_values_are_never_logged(monkeypatch, capsys, success):
    monkeypatch.setenv("FUNCTION_APP_NAME", "app")
    monkeypatch.setenv("RESOURCE_GROUP_NAME", "group")
    run = MagicMock(return_value=MagicMock(returncode=0 if success else 1, stdout="{}", stderr="secret-output"))
    monkeypatch.setattr(validation.subprocess, "run", run)
    if success:
        validation.az("config", "appsettings", "set", "--settings", "TOKEN=secret-value")
    else:
        with pytest.raises(RuntimeError) as caught:
            validation.az("config", "appsettings", "set", "--settings", "TOKEN=secret-value")
        assert "secret" not in str(caught.value)
    output = capsys.readouterr()
    assert "secret" not in output.out + output.err


@pytest.mark.parametrize("binding_type,schedule", [(None, None), ("httpTrigger", None), ("timerTrigger", "0 */5 * * * *")])
def test_readiness_supports_app_specific_expectations(monkeypatch, binding_type, schedule):
    monkeypatch.setattr(validation, "az", MagicMock(side_effect=[
        {"defaultHostName": "test.azurewebsites.net"},
        {"masterKey": "private-key"},
        [{"name": "app/other_function", "config": {"bindings": [
            {"type": binding_type or "httpTrigger", "schedule": schedule},
        ]}}],
    ]))
    request = MagicMock(return_value=(200, {"state": "Running"}))
    monkeypatch.setattr(validation, "host_request", request)
    assert validation.wait_for_function("other_function", binding_type=binding_type, schedule=schedule) == (
        "test.azurewebsites.net", "private-key",
    )
    request.assert_called_once_with("test.azurewebsites.net", "private-key", "/admin/host/status")


@pytest.mark.parametrize("difference", ["name", "type", "schedule"])
def test_readiness_rejects_wrong_function_or_trigger(monkeypatch, difference):
    binding = {"type": "timerTrigger", "schedule": "0 */5 * * * *"}
    function = {"name": "app/expected", "config": {"bindings": [binding]}}
    if difference == "name":
        function["name"] = "app/other"
    elif difference == "type":
        binding["type"] = "httpTrigger"
    else:
        binding["schedule"] = "0 0 * * * *"
    monkeypatch.setattr(validation, "az", MagicMock(side_effect=[
        {"defaultHostName": "test.azurewebsites.net"}, {"masterKey": "key"}, [function],
    ]))
    monkeypatch.setattr(validation, "host_request", MagicMock(return_value=(200, {"state": "Running"})))
    with pytest.raises(RuntimeError, match="Timed out"):
        validation.wait_for_function("expected", binding_type="timerTrigger", schedule="0 */5 * * * *", timeout=0)


def test_admin_key_is_not_forwarded_on_redirect():
    assert validation.NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://other.example") is None


def test_module_imports_without_site_packages(tmp_path):
    import os
    from pathlib import Path
    import subprocess
    import sys
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[3] / "python"))
    subprocess.run([
        sys.executable, "-S", "-c",
        "from platform_azure_functions import deployment; assert callable(deployment.preflight)",
    ], cwd=tmp_path, env=env, check=True)
