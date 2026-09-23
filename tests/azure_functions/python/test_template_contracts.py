"""Fast structural regression checks, not an Azure YAML expression evaluator."""
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = ROOT / "templates/azure-functions/python/ci-cd.yml"
CI = ROOT / "templates/azure-functions/python/ci/stages.yml"
CD = ROOT / "templates/azure-functions/python/cd/stages.yml"


def read_yaml(path):
    return yaml.safe_load(path.read_text())


def mappings(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from mappings(child)


def test_example_parameters_remain_compatible():
    declared = {p["name"]: p for p in read_yaml(TEMPLATE)["parameters"]}
    example = read_yaml(ROOT / "examples/azure-functions/python/azure-pipelines.yml")
    supplied = example["extends"]["parameters"]
    assert supplied.keys() <= declared.keys(), "Starter uses removed/renamed parameters"
    required = {name for name, p in declared.items() if "default" not in p}
    assert required <= supplied.keys(), "Starter omits required parameters"
    assert example["extends"]["template"].split("@")[0] == "/" + str(TEMPLATE.relative_to(ROOT))


def test_deployment_is_opt_in_and_guarded():
    template = read_yaml(CD)
    defaults = {p["name"]: p.get("default") for p in template["parameters"]}
    assert defaults["deploy"] is False
    deploy = template["stages"][0]["${{ if eq(parameters.deploy, true) }}"][0]
    assert defaults["dependsOn"] == ["Build"]
    assert deploy["dependsOn"] == "${{ parameters.dependsOn }}"
    # Deliberate contract: losing any guard can expose production to failed/PR builds.
    assert deploy["condition"] == (
        "and(succeeded(), eq(variables['Build.SourceBranch'], "
        "'${{ parameters.deploymentBranch }}'), ne(variables['Build.Reason'], 'PullRequest'))"
    )


def test_reports_are_required_and_deployment_uses_current_artifact():
    nodes = list(mappings([read_yaml(CI), read_yaml(CD)]))
    reports = next(n for n in nodes if n.get("task") == "PublishTestResults@2")
    assert reports["inputs"]["failTaskOnFailedTests"] is True
    assert reports["inputs"]["failTaskOnMissingResultsFile"] is True
    coverage = next(n for n in nodes if n.get("task") == "PublishCodeCoverageResults@2")
    assert coverage["inputs"]["failIfCoverageEmpty"] is True
    published = next(n for n in nodes if "publish" in n)
    download = next(n for n in nodes if "download" in n and "artifact" in n)
    assert download["download"] == "${{ parameters.artifactPipeline }}"
    assert next(p["default"] for p in read_yaml(CD)["parameters"] if p["name"] == "artifactPipeline") == "current"
    assert download["artifact"] == published["artifact"]
    deploy = next(n for n in nodes if n.get("task") == "AzureFunctionApp@2")
    expected = f"$(Pipeline.Workspace)/{published['artifact']}/{Path(published['publish']).name}"
    assert deploy["inputs"]["package"] == "$(functionPackagePath)"
    assert any(n.get("functionPackagePath") == expected for n in nodes)
    assert any(n.get("artifactBuildId") == "$(Build.BuildId)" and
               n.get("artifactSourceVersion") == "$(Build.SourceVersion)" for n in nodes)
    archive = next(n for n in nodes if n.get("task") == "ArchiveFiles@2")
    assert archive["inputs"]["includeRootFolder"] is False
    assert archive["inputs"]["archiveFile"] == published["publish"]


def test_platform_validation_executes_candidate_without_deploying():
    pipeline = read_yaml(ROOT / ".azure-pipelines/validation/azure-functions-python.yml")
    smoke = next(s for s in pipeline["stages"] if "template" in s)
    assert smoke["template"] == "/" + str(CI.relative_to(ROOT))
    assert "@" not in smoke["template"], "Must test the candidate, not a remote release"
    assert "deploy" not in smoke["parameters"]
    assert "resources" not in pipeline, "Build-only validation needs no external repo"


def test_container_stage_tests_current_artifact_and_matching_runtime():
    version = next(p["default"] for p in read_yaml(TEMPLATE)["parameters"] if p["name"] == "pythonVersion")
    workload = read_yaml(ROOT / ".azure-pipelines/validation/azure-functions-python.yml")
    stage = next(s for s in workload["stages"] if s.get("stage") == "ContainerSmoke")
    assert stage["variables"]["functionsTestImage"] == f"mcr.microsoft.com/azure-functions/python:4-python{version}"
    assert stage["dependsOn"] == "InspectArtifact"
    nodes = list(mappings(stage))
    assert any(n.get("download") == "current" and n.get("artifact") == "function-package" for n in nodes)
    assert not any(n.get("continueOnError") for n in nodes)
    runner = next(n for n in nodes if "bash" in n)
    assert "tests/azure_functions/python/container_smoke.py" in runner["bash"]
    assert runner["env"]["PACKAGE_ZIP"] == "$(Pipeline.Workspace)/function-package/function-app.zip"


def test_hosting_modes_and_hook_order_remain_supported():
    template = read_yaml(CI)
    build = template["stages"][0]["jobs"][0]["steps"]
    hook = build.index("${{ parameters.packageValidationSteps }}")
    validate = next(i for i, step in enumerate(build) if isinstance(step, dict)
                    and step.get("displayName") == "Validate and compile deployment package")
    archive = next(i for i, step in enumerate(build) if isinstance(step, dict)
                   and step.get("task") == "ArchiveFiles@2")
    assert hook < validate < archive
    stage = read_yaml(CD)["stages"][0]["${{ if eq(parameters.deploy, true) }}"][0]
    steps = stage["jobs"][0]["strategy"]["runOnce"]["deploy"]["steps"]
    deploy_index = next(i for i, step in enumerate(steps) if isinstance(step, dict)
                        and step.get("task") == "AzureFunctionApp@2")
    assert steps.index("${{ parameters.beforeDeploySteps }}") < deploy_index
    assert deploy_index < steps.index("${{ parameters.afterDeploySteps }}")
    inputs = steps[deploy_index]["inputs"]
    assert inputs["isFlexConsumption"] == "${{ parameters.isFlexConsumption }}"
    assert inputs["${{ if eq(parameters.isFlexConsumption, false) }}"]["deploymentMethod"] == "zipDeploy"


def test_compatibility_wrapper_forwards_every_parameter_with_matching_defaults():
    wrapper = read_yaml(TEMPLATE)
    original = {p["name"]: p for p in wrapper["parameters"]}
    forwarded = set()
    for call in wrapper["stages"]:
        component = read_yaml(ROOT / call["template"].lstrip("/"))
        declared = {p["name"]: p for p in component["parameters"]}
        assert call["parameters"].keys() <= declared.keys()
        omitted = declared.keys() - call["parameters"].keys()
        assert all("default" in declared[name] for name in omitted)
        for name, value in call["parameters"].items():
            assert value == "${{ parameters." + name + " }}"
            assert declared[name] == original[name]
            forwarded.add(name)
    assert forwarded == original.keys()
    assert len(wrapper["stages"]) == 2


def test_ci_contains_no_deployment_tasks_or_inputs():
    ci = read_yaml(CI)
    declared = {p["name"] for p in ci["parameters"]}
    assert not declared & {"deploy", "azureServiceConnection", "functionAppName", "environment"}
    for node in mappings(ci):
        assert "deployment" not in node
        assert node.get("task") != "AzureFunctionApp@2"
    assert not any("publish" in n or n.get("task") == "ArchiveFiles@2" for n in mappings(read_yaml(CD)))


@pytest.mark.parametrize("example", ["ci.yml", "cd.yml", "ci-cd.yml"])
def test_component_examples_supply_valid_parameters(example):
    pipeline = read_yaml(ROOT / "examples/azure-functions/python" / example)
    for call in pipeline["stages"]:
        path = ROOT / call["template"].split("@")[0].lstrip("/")
        declared = {p["name"]: p for p in read_yaml(path)["parameters"]}
        supplied = call.get("parameters", {})
        assert supplied.keys() <= declared.keys()
        assert {name for name, p in declared.items() if "default" not in p} <= supplied.keys()


def test_standalone_cd_uses_completion_trigger_and_selected_run():
    pipeline = read_yaml(ROOT / "examples/azure-functions/python/cd.yml")
    assert pipeline["trigger"] == "none"
    resource = pipeline["resources"]["pipelines"][0]
    assert resource["trigger"]["branches"]["include"] == ["refs/heads/main"]
    assert "stages" not in resource["trigger"], "Wait for ALL CI stages, including integration tests"
    params = pipeline["stages"][0]["parameters"]
    assert params["artifactPipeline"] == resource["pipeline"]
    assert params["dependsOn"] == []
    nodes = list(mappings(read_yaml(CD)))
    assert any(n.get("download") == "none" for n in nodes)
    assert any(n.get("functionPackagePath") == "$(Pipeline.Workspace)/${{ parameters.artifactPipeline }}/function-package/function-app.zip" for n in nodes)
    assert any(n.get("artifactBuildId") == "$(resources.pipeline.${{ parameters.artifactPipeline }}.runID)" and
               n.get("artifactSourceVersion") == "$(resources.pipeline.${{ parameters.artifactPipeline }}.sourceCommit)" for n in nodes)
    stage = read_yaml(CD)["stages"][0]["${{ if eq(parameters.deploy, true) }}"][0]
    steps = stage["jobs"][0]["strategy"]["runOnce"]["deploy"]["steps"]
    verification = next(i for i, step in enumerate(steps) if isinstance(step, dict)
                        and "${{ if ne(parameters.artifactPipeline, 'current') }}" in step)
    download = next(i for i, step in enumerate(steps) if isinstance(step, dict) and "artifact" in step)
    assert verification < download < steps.index("${{ parameters.beforeDeploySteps }}")
