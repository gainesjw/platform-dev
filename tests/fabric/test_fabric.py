"""Offline Fabric governance, promotion and real YAML release-gate tests."""

import io
import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock
import urllib.request
from uuid import uuid4

import pytest
import yaml

from platform_fabric import deploy as deployment
from platform_fabric.inventory import generate, read_json, write_json, write_inventory
from platform_fabric.release import build, verify
from platform_fabric.policy import request_payload, review, validate_review

PLATFORM = Path(__file__).resolve().parents[2]


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    lake, notebook, source_workspace = [str(uuid4()) for _ in range(3)]
    config = dict(schemaVersion=1, repository="engineering", itemRoots=["items"],
                  allowedItemTypes=["Lakehouse", "Notebook"], sourceWorkspaceId=source_workspace,
                  governance=dict(owner="engineering", classification="internal"),
                  environments={e: dict(workspaceId=str(uuid4())) for e in ("dev", "test", "prod")})
    for kind, name, key in [("Lakehouse", "lake", lake), ("Notebook", "ingest", notebook)]:
        folder = root / "items" / (name + "." + kind)
        write_json(folder / ".platform", dict(metadata=dict(type=kind, displayName=name), config=dict(logicalId=key)))
        if kind == "Lakehouse":
            write_json(folder / "lakehouse.metadata.json", {"defaultSchema": "dbo"})
        else:
            physical = str(uuid4())
            meta = dict(dependencies=dict(lakehouse=dict(default_lakehouse=physical, default_lakehouse_name="lake",
                        default_lakehouse_workspace_id=source_workspace, known_lakehouses=[dict(id=physical)])))
            (folder / "notebook-content.py").write_text("\n".join("# META " + line for line in json.dumps(meta, indent=2).splitlines()) + "\n")
    write_json(root / ".fabric/config.json", config)
    return root, config, lake, notebook


def test_inventory_is_deterministic_and_orders_prerequisites(workspace, tmp_path):
    root, config, lake, notebook = workspace
    manifest, graph = generate(root, config)
    assert manifest["deploymentOrder"] == [lake, notebook]
    assert graph["edges"][0]["dependency"] == lake
    assert manifest["bindings"][0]["target"] == "item:" + lake
    write_inventory(tmp_path / "a", manifest, graph)
    write_inventory(tmp_path / "b", *generate(root, config))
    for path in (tmp_path / "a").iterdir():
        assert path.read_bytes() == (tmp_path / "b" / path.name).read_bytes()


@pytest.mark.parametrize("mutation,match", [
    ("duplicate", "Duplicate"), ("missing", "Missing .platform"),
    ("unknown_lake", "Unresolved notebook"), ("cycle", "cycle"),
    ("scope", "outside governance scope"), ("owner", "Missing governance"),
    ("workspace", "Unexpected source workspace"), ("escape", "Unsafe relative path"),
])
def test_invalid_governance_fails_closed(workspace, mutation, match):
    root, config, lake, notebook = workspace
    metadata = root / "items/ingest.Notebook/.platform"
    if mutation == "duplicate":
        data = read_json(metadata)
        data["config"]["logicalId"] = lake
        write_json(metadata, data)
    elif mutation == "missing":
        metadata.unlink()
    elif mutation == "unknown_lake":
        path = root / "items/ingest.Notebook/notebook-content.py"
        path.write_text(path.read_text().replace('"lake"', '"missing"'))
    elif mutation == "cycle":
        config["dependencies"] = [dict(item=lake, dependency=notebook)]
    elif mutation == "scope":
        config["allowedItemTypes"] = ["Notebook"]
    elif mutation == "owner":
        config["governance"]["owner"] = ""
    elif mutation == "workspace":
        config["sourceWorkspaceId"] = str(uuid4())
    elif mutation == "escape":
        config["itemRoots"] = ["../source/items"]
    with pytest.raises(ValueError, match=match):
        generate(root, config)


def test_new_items_are_automatically_included(workspace):
    root, config, _, _ = workspace
    folder = root / "items/other.Lakehouse"
    write_json(folder / ".platform", dict(metadata=dict(type="Lakehouse", displayName="other"),
                                          config=dict(logicalId=str(uuid4()))))
    write_json(folder / "lakehouse.metadata.json", {})
    assert len(generate(root, config)[0]["items"]) == 3


def test_symlink_is_rejected(workspace):
    root, config, _, _ = workspace
    (root / "items/linked").symlink_to(root / ".fabric/config.json")
    with pytest.raises(ValueError, match="Symlinks"):
        generate(root, config)


@pytest.mark.parametrize("mutation", ["edit", "add", "remove", "config", "tooling", "requirements"])
def test_release_rejects_any_modified_file_set(workspace, tmp_path, mutation):
    root, _, _, _ = workspace
    output = tmp_path / "release"
    build(root, output, {"buildId": "42"})
    verify(output, {"buildId": "42"})
    path = output / "workspace/items/lake.Lakehouse/lakehouse.metadata.json"
    if mutation == "edit":
        path.write_text("{}")
    elif mutation == "add":
        (output / "unexpected").write_text("extra")
    elif mutation == "remove":
        path.unlink()
    elif mutation == "config":
        (output / "config.json").write_text("{}")
    elif mutation == "requirements":
        (output / "tooling/requirements.txt").write_text("fabric-cicd==0.0.0\n")
    else:
        (output / "tooling/platform_fabric/deploy.py").write_text("modified")
    with pytest.raises(ValueError, match="integrity"):
        verify(output)


def test_release_rejects_mismatched_provenance(workspace, tmp_path):
    root, _, _, _ = workspace
    build(root, tmp_path / "release", {"buildId": "42"})
    with pytest.raises(ValueError, match="provenance"):
        verify(tmp_path / "release", {"buildId": "43"})


def test_target_checks(workspace):
    _, config, _, _ = workspace
    deployment.validate_target(config, "dev")
    config["environments"]["test"] = config["environments"]["dev"].copy()
    with pytest.raises(ValueError, match="distinct"):
        deployment.validate_target(config, "dev")
    config["environments"]["dev"]["workspaceId"] = "REPLACE_WITH_DEV_ID"
    with pytest.raises(ValueError):
        deployment.validate_target(config, "dev")


def test_notebook_parameterization_scoped_to_item(workspace):
    root, config, _, _ = workspace
    manifest, _ = generate(root, config)
    rules = deployment.parameter_document(manifest, config, "test", {})["find_replace"]
    assert rules[0]["replace_value"] == {"test": "$items.Lakehouse.lake.$id"}
    assert rules[0]["item_type"] == "Notebook"
    assert rules[0]["item_name"] == "ingest"
    assert rules[1]["replace_value"] == {"test": config["environments"]["test"]["workspaceId"]}


def test_deployment_receipt_and_no_deletion(workspace, tmp_path, monkeypatch):
    root, _, lake, notebook = workspace
    output = tmp_path / "release"
    build(root, output, {"buildId": "42"})
    api = MagicMock()
    unmanaged = dict(id=str(uuid4()), type="Lakehouse", displayName="unmanaged")
    api.items.side_effect = [[unmanaged], [unmanaged,
        dict(id="lake-id", type="Lakehouse", displayName="lake"),
        dict(id="notebook-id", type="Notebook", displayName="ingest")]]
    monkeypatch.setattr(deployment, "FabricAPI", lambda credential: api)
    publisher = MagicMock()
    deployment.deploy(output, "dev", tmp_path / "receipt.json", {"buildId": "42"}, object(), publisher)
    receipt = read_json(tmp_path / "receipt.json")
    assert receipt["status"] == "succeeded"
    assert receipt["plan"]["delete"] == []
    assert receipt["plan"]["unmanagedRetained"] == [["Lakehouse", "unmanaged"]]
    assert {i["logicalId"] for i in receipt["items"]} == {lake, notebook}
    publisher.assert_called_once()
    verify(output)  # Deployment did not change the release.


def test_failed_postcheck_fails_promotion(workspace, tmp_path, monkeypatch):
    root, _, _, _ = workspace
    output = tmp_path / "release"
    build(root, output, {})
    api = MagicMock()
    api.items.return_value = []
    monkeypatch.setattr(deployment, "FabricAPI", lambda credential: api)
    with pytest.raises(ValueError, match="Post-deployment"):
        deployment.deploy(output, "dev", tmp_path / "receipt.json", {}, object(), MagicMock())
    assert read_json(tmp_path / "receipt.json")["status"] == "failed"


def test_pagination_preserves_all_items():
    api = deployment.FabricAPI(object())
    api.get = MagicMock(side_effect=[dict(value=[1], continuationToken="a/b"), dict(value=[2])])
    assert api.items(str(uuid4())) == [1, 2]
    assert api.get.call_args.args[0].endswith("?continuationToken=a%2Fb")


@pytest.fixture
def analytics(tmp_path):
    root = tmp_path / "analytics"
    model, report = str(uuid4()), str(uuid4())
    for kind, key in [("SemanticModel", model), ("Report", report)]:
        folder = root / "projects" / ("product." + kind)
        write_json(folder / ".platform", dict(metadata=dict(type=kind, displayName="product"), config=dict(logicalId=key)))
        if kind == "Report":
            write_json(folder / "definition.pbir", dict(datasetReference=dict(byPath=dict(path="../product.SemanticModel"))))
        else:
            write_json(folder / "definition.pbism", dict(version="4.0"))
            (folder / "source.tmdl").write_text('Source = Sql.Database("__SQL__", "lake")')
    config = dict(schemaVersion=1, repository="analytics", itemRoots=["projects"],
        allowedItemTypes=["SemanticModel", "Report"], governance=dict(owner="analytics", classification="internal"),
        environments={e: dict(workspaceId=str(uuid4()), semanticModelConnectionId=str(uuid4())) for e in ["dev", "test", "prod"]},
        externalDependencies={"lake": dict(type="Lakehouse", itemName="lake", sourceToken="__SQL__",
            repository="engineering", owner="engineering", environments={e: dict(workspaceId=str(uuid4())) for e in ["dev", "test", "prod"]})})
    return root, config, model, report


def test_analytics_lineage_and_external_binding(analytics):
    root, config, model, report = analytics
    manifest, graph = generate(root, config)
    assert manifest["deploymentOrder"] == [model, report]
    assert {(e["item"], e["dependency"]) for e in graph["edges"]} == {(report, model), (model, "external:lake")}
    api = MagicMock()
    api.items.return_value = [dict(type="Lakehouse", displayName="lake", id=str(uuid4()))]
    endpoint = "test.datawarehouse.fabric.microsoft.com"
    api.get.return_value = dict(properties=dict(sqlEndpointProperties=dict(connectionString=endpoint, provisioningStatus="Success")))
    external = deployment.resolve_external(config, "test", api)
    api.items.assert_called_once_with(config["externalDependencies"]["lake"]["environments"]["test"]["workspaceId"])
    params = deployment.parameter_document(manifest, config, "test", external)
    assert params["find_replace"][0]["replace_value"] == {"test": endpoint}
    assert params["semantic_model_binding"]["default"]["connection_id"]["test"] == config["environments"]["test"]["semanticModelConnectionId"]


@pytest.mark.parametrize("case", ["missing_model", "undeclared_sql", "external_not_ready", "external_missing"])
def test_broken_analytics_dependencies_fail(analytics, case):
    root, config, _, _ = analytics
    if case == "missing_model":
        write_json(root / "projects/product.Report/definition.pbir", dict(datasetReference=dict(byPath=dict(path="../missing"))))
    elif case == "undeclared_sql":
        config["externalDependencies"] = {}
    if case in {"missing_model", "undeclared_sql"}:
        with pytest.raises(ValueError):
            generate(root, config)
    else:
        api = MagicMock()
        api.items.return_value = [] if case == "external_missing" else [dict(type="Lakehouse", displayName="lake", id=str(uuid4()))]
        api.get.return_value = dict(properties=dict(sqlEndpointProperties=dict(provisioningStatus="InProgress")))
        with pytest.raises(ValueError):
            deployment.resolve_external(config, "prod", api)


def test_unconfigured_target_makes_no_api_or_publish_calls(workspace, tmp_path, monkeypatch):
    root, config, _, _ = workspace
    config["environments"]["dev"]["workspaceId"] = "REPLACE_WITH_DEV"
    write_json(root / ".fabric/config.json", config)
    release = tmp_path / "release"
    build(root, release, {})
    api, publisher = MagicMock(), MagicMock()
    monkeypatch.setattr(deployment, "FabricAPI", api)
    with pytest.raises(ValueError):
        deployment.deploy(release, "dev", tmp_path / "receipt.json", {}, object(), publisher)
    api.assert_not_called()
    publisher.assert_not_called()


@pytest.mark.parametrize("change", [{}, {"result": "failed"}, {"result": "partiallySucceeded"},
    {"status": "inProgress"}, {"reason": "pullRequest"}, {"sourceBranch": "refs/heads/feature"},
    {"repository": {"id": "wrong"}}, {"sourceVersion": "wrong"}, {"definition": {"id": 8}}, {"id": 43}])
def test_real_fabric_yaml_release_gate(monkeypatch, change):
    step = yaml.safe_load((PLATFORM / "templates/fabric/cd/verify-ci-run.yml").read_text())["steps"][0]
    script = step["bash"].split("python - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    for key, value in dict(CI_RUN_ID="42", CI_PIPELINE_ID="7", COLLECTION_URI="https://dev.azure.com/example/",
                           PROJECT_ID="project", SYSTEM_ACCESSTOKEN="secret", APP_REPOSITORY_ID="repo",
                           APP_SOURCE_VERSION="commit", CI_SOURCE_VERSION="commit").items():
        monkeypatch.setenv(key, value)
    response = dict(id=42, status="completed", result="succeeded", reason="individualCI",
                    definition={"id": 7}, repository={"id": "repo"}, sourceVersion="commit", sourceBranch="refs/heads/main")
    response.update(change)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: io.StringIO(json.dumps(response)))
    if change:
        with pytest.raises(RuntimeError):
            exec(compile(script, "fabric-gate", "exec"), {})
    else:
        exec(compile(script, "fabric-gate", "exec"), {})


def test_template_isolation_and_promotion_chain():
    paths = list((PLATFORM / "templates/fabric/ci").glob("*.yml")) + list((PLATFORM / "templates/fabric/cd").glob("*.yml"))
    for path in paths:
        text = path.read_text()
        yaml.safe_load(text)
        assert "azure-functions/" not in text
        assert "AzureFunctionApp@" not in text
    cd = yaml.safe_load((PLATFORM / "templates/fabric/cd/stages.yml").read_text())
    stages = cd["stages"]
    assert [s["parameters"]["name"] for s in stages] == ["dev", "test", "prod"]
    assert stages[1]["parameters"]["dependsOn"] == ["Fabric_dev"]
    assert stages[2]["parameters"]["dependsOn"] == ["Fabric_test"]


def policy_receipt(release, passing):
    payload = request_payload(release, "dev")
    request = json.loads(payload)
    return dict(decisionId=str(uuid4()), workspaceId=request["workspaceId"], environment="dev",
                policyVersion="test", policyDigest="a" * 64, requestDigest=hashlib.sha256(payload).hexdigest(),
                manifest=request["manifest"], findings=[], items=[dict(logicalId=i["logicalId"], approved=i["logicalId"] in passing,
                    findings=[] if i["logicalId"] in passing else [dict(code="item.owner", message="Owner fails")])
                    for i in request["manifest"]["items"]])


def test_partial_deployment_only_exposes_passing_files_to_sdk(workspace, tmp_path, monkeypatch):
    import sys
    root, _, lake, notebook = workspace
    release, receipt, policy_path = (tmp_path / p for p in ("release", "receipt.json", "policy.json"))
    build(root, release, {})
    write_json(policy_path, policy_receipt(release, {lake}))
    api = MagicMock()
    api.items.side_effect = [[], [dict(id="lake-id", type="Lakehouse", displayName="lake")]]
    monkeypatch.setattr(deployment, "FabricAPI", lambda credential: api)
    sdk = MagicMock()
    def inspect_workspace(**kwargs):
        work = Path(kwargs["repository_directory"])
        assert (work / "items/lake.Lakehouse/.platform").exists()
        assert not (work / "items/ingest.Notebook").exists()
        assert read_json(work / "parameter.yml") == {}
        assert kwargs["item_type_in_scope"] == ["Lakehouse"]
        return object()
    sdk.FabricWorkspace.side_effect = inspect_workspace
    monkeypatch.setitem(sys.modules, "fabric_cicd", sdk)
    deployment.deploy(release, "dev", receipt, {}, object(), policy_review=policy_path)
    result = read_json(receipt)
    assert result["status"] == "succeeded"
    assert result["selectedItemIds"] == [lake]
    assert result["skippedItems"][0]["logicalId"] == notebook
    assert result["skippedItems"][0]["findings"]
    assert [i["logicalId"] for i in result["items"]] == [lake]
    sdk.publish_all_items.assert_called_once()
    verify(release)


@pytest.mark.parametrize("case", ["none", "dependency", "all", "wrong_release"])
def test_policy_selection_before_any_fabric_calls(workspace, tmp_path, monkeypatch, case):
    root, _, lake, notebook = workspace
    release, receipt, policy_path = (tmp_path / p for p in ("release", "receipt.json", "policy.json"))
    build(root, release, {})
    result = policy_receipt(release, set() if case == "none" else {notebook} if case == "dependency" else {lake})
    if case == "wrong_release":
        result["requestDigest"] = "0" * 64
    write_json(policy_path, result)
    api, publisher = MagicMock(), MagicMock()
    monkeypatch.setattr(deployment, "FabricAPI", api)
    def invoke():
        deployment.deploy(release, "dev", receipt, {}, object(), publisher, policy_review=policy_path,
                          policy_mode="all" if case == "all" else "passing")
    if case == "none":
        invoke()
        assert read_json(receipt)["status"] == "skipped"
        assert len(read_json(receipt)["skippedItems"]) == 2
    else:
        with pytest.raises(ValueError, match={"dependency": "prerequisite", "all": "all items", "wrong_release": "digest"}[case]):
            invoke()
    api.assert_not_called()
    publisher.assert_not_called()


@pytest.mark.parametrize("case", ["workspace", "environment", "manifest", "missing", "duplicate", "boolean", "findings", "global", "pin"])
def test_invalid_policy_receipts_are_rejected(workspace, tmp_path, case):
    root, _, lake, _ = workspace
    release = tmp_path / "release"
    build(root, release, {})
    result = policy_receipt(release, {lake})
    passing = next(i for i in result["items"] if i["approved"])
    if case == "workspace": result["workspaceId"] = str(uuid4())
    if case == "environment": result["environment"] = "prod"
    if case == "manifest": result["manifest"]["items"].pop()
    if case == "missing": result["items"].pop()
    if case == "duplicate": result["items"].append(result["items"][0])
    if case == "boolean": passing["approved"] = "true"
    if case == "findings": passing["findings"] = [dict(code="failed")]
    if case == "global": result["findings"] = [dict(code="workspace.repository")]
    with pytest.raises(ValueError):
        validate_review(result, request_payload(release, "dev"), "dev", "b" * 64 if case == "pin" else None)


def test_review_collects_failures_without_deciding_deployment(workspace, tmp_path, monkeypatch):
    from platform_fabric import policy
    root, _, _, _ = workspace
    release, receipt = tmp_path / "release", tmp_path / "policy.json"
    build(root, release, {})
    result = policy_receipt(release, set())
    response = MagicMock()
    response.__enter__.return_value = io.StringIO(json.dumps(result))
    response.__enter__.return_value.status = 200
    opener = MagicMock()
    opener.open.return_value = response
    monkeypatch.setattr(policy, "build_opener", lambda *args: opener)
    assert review(release, "dev", "https://policy.example", receipt, {}) == result
    assert read_json(receipt) == result
    request = opener.open.call_args.args[0]
    assert request.data == request_payload(release, "dev")


def test_pipeline_collects_review_before_selective_deployment():
    pipeline = yaml.safe_load((PLATFORM / "templates/fabric/cd/environment.yml").read_text())
    steps = pipeline["stages"][0]["jobs"][0]["strategy"]["runOnce"]["deploy"]["steps"]
    review_index = next(i for i, step in enumerate(steps) if "${{ if ne(parameters.policyApiUrl, '') }}" in step)
    deploy_index = next(i for i, step in enumerate(steps) if step.get("task") == "AzureCLI@2")
    assert review_index < deploy_index
    assert "--policy-review" in steps[deploy_index]["inputs"]["inlineScript"]
    assert "--policy-mode" in steps[deploy_index]["inputs"]["inlineScript"]


def test_skipped_models_do_not_require_external_or_connection_configuration(analytics, tmp_path, monkeypatch):
    root, config, _, _ = analytics
    lake = str(uuid4())
    folder = root / "projects/independent.Lakehouse"
    write_json(folder / ".platform", dict(metadata=dict(type="Lakehouse", displayName="independent"),
                                          config=dict(logicalId=lake)))
    write_json(folder / "lakehouse.metadata.json", {})
    config["allowedItemTypes"].append("Lakehouse")
    config["environments"]["dev"]["semanticModelConnectionId"] = "not-configured"
    config["externalDependencies"]["lake"]["environments"]["dev"]["workspaceId"] = "not-configured"
    write_json(root / ".fabric/config.json", config)
    release, receipt, policy_path = (tmp_path / p for p in ("release", "receipt.json", "policy.json"))
    build(root, release, {})
    write_json(policy_path, policy_receipt(release, {lake}))
    api = MagicMock()
    api.items.return_value = [dict(id=lake, type="Lakehouse", displayName="independent")]
    monkeypatch.setattr(deployment, "FabricAPI", lambda credential: api)
    deployment.deploy(release, "dev", receipt, {}, object(), MagicMock(), policy_review=policy_path)
    assert read_json(receipt)["status"] == "succeeded"
    assert read_json(receipt)["externalDependencies"] == {}
    assert all(call.args == (config["environments"]["dev"]["workspaceId"],) for call in api.items.call_args_list)
