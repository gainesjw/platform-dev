"""Cross-workload placement, entry point and example contracts."""

import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CATALOG = json.loads((ROOT / "catalog.json").read_text())


@pytest.mark.parametrize("path", sorted(
    list((ROOT / "templates").rglob("*.yml"))
    + list((ROOT / "examples").rglob("*.yml"))
    + list((ROOT / ".azure-pipelines").rglob("*.yml"))
), ids=lambda path: str(path.relative_to(ROOT)))
def test_yaml_is_a_mapping(path):
    assert isinstance(yaml.safe_load(path.read_text()), dict)


@pytest.mark.parametrize("name,entry", CATALOG["workloads"].items())
def test_catalog_is_complete_and_resolves(name, entry):
    assert CATALOG["schemaVersion"] == 1
    for field in ["templateRoot", "ci", "cd", "validation", "examples", "documentation", "tests", "pythonPackage", "testRequirements"]:
        path = ROOT / entry[field]
        assert path.resolve().is_relative_to(ROOT)
        assert path.exists(), f"{name}: missing {field}: {path}"
    assert entry["ci"] == entry["templateRoot"] + "/ci/stages.yml"
    assert entry["cd"] == entry["templateRoot"] + "/cd/stages.yml"
    assert entry["templateRoot"].removeprefix("templates/") == entry["examples"].removeprefix("examples/")
    assert entry["templateRoot"].removeprefix("templates/") == entry["documentation"].removeprefix("docs/")
    assert entry["artifact"] and entry["pythonVersion"]
    if entry["deploymentRequirements"]:
        assert (ROOT / entry["deploymentRequirements"]).is_file()
    if entry["combined"]:
        assert entry["combined"] == entry["templateRoot"] + "/ci-cd.yml"
        assert (ROOT / entry["combined"]).is_file()
    for phase in ["ci", "cd"]:
        assert (ROOT / entry["examples"] / (phase + ".yml")).is_file()


def test_workloads_have_distinct_artifacts_and_packages():
    workloads = list(CATALOG["workloads"].values())
    for field in ["artifact", "pythonPackage", "tests", "examples", "documentation"]:
        assert len({w[field] for w in workloads}) == len(workloads)


def test_registered_platform_validation_entry_point_composes_every_workload():
    entry_path = ROOT / ".azure-pipelines/azure-pipelines.yml"
    pipeline = yaml.safe_load(entry_path.read_text())
    assert set(pipeline) == {"trigger", "pool", "stages"}
    actual = {(entry_path.parent / s["template"]).relative_to(ROOT).as_posix() for s in pipeline["stages"]}
    assert actual == {w["validation"] for w in CATALOG["workloads"].values()}
    assert all("jobs" not in s for s in pipeline["stages"])


@pytest.mark.parametrize("example", ["ci", "cd"])
def test_fabric_starter_uses_the_catalog_entry_points(example):
    entry = CATALOG["workloads"]["fabric-workspace"]
    pipeline = yaml.safe_load((ROOT / entry["examples"] / (example + ".yml")).read_text())
    assert pipeline["extends"]["template"] == "/" + entry[example] + "@platform"
    template = yaml.safe_load((ROOT / entry[example]).read_text())
    declared = {p["name"]: p for p in template["parameters"]}
    supplied = pipeline["extends"].get("parameters", {})
    assert supplied.keys() <= declared.keys()
    assert {k for k, v in declared.items() if "default" not in v} <= supplied.keys()
