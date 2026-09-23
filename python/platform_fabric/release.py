"""Package one immutable, attributable Fabric release for all environments."""

import os
import shutil
from pathlib import Path

from .inventory import contained, digest, files, generate, read_json, require, write_inventory, write_json


def build(root, output, provenance):
    root, output = Path(root).resolve(), Path(output).resolve()
    require(not output.exists(), "Release output must not exist; use a fresh directory")
    config = read_json(root / ".fabric/config.json")
    manifest, graph = generate(root, config)
    output.mkdir(parents=True)
    for item in manifest["items"]:
        for name in item["files"]:
            destination = output / "workspace" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(contained(root, name), destination)
    write_json(output / "config.json", config)
    write_inventory(output / "inventory", manifest, graph)
    write_json(output / "provenance.json", provenance)
    # Capture tooling with the release: later stages never load mutable main Python.
    shutil.copytree(Path(__file__).parent, output / "tooling/platform_fabric",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(Path(__file__).resolve().parents[2] / "requirements/fabric/runtime.txt",
                 output / "tooling/requirements.txt")
    write_json(output / "checksums.json", {p.relative_to(output).as_posix(): digest(p) for p in files(output)})
    verify(output)


def verify(output, expected=None):
    output = Path(output)
    checksums = read_json(output / "checksums.json")
    actual = {p.relative_to(output).as_posix(): digest(p) for p in files(output) if p != output / "checksums.json"}
    require(checksums == actual, "Release file set or SHA-256 integrity check failed")
    provenance = read_json(output / "provenance.json")
    for key, value in (expected or {}).items():
        require(value and provenance.get(key) == value, f"Release provenance mismatch: {key}")
    manifest, graph = generate(output / "workspace", read_json(output / "config.json"))
    require(manifest == read_json(output / "inventory/manifest.json"), "Release inventory differs from source")
    require(graph == read_json(output / "inventory/dependencies.json"), "Release graph differs from source")
    return provenance


def pipeline_provenance():
    return {key: os.environ.get(variable, "local") for key, variable in {
        "buildId": "BUILD_BUILDID", "sourceVersion": "BUILD_SOURCEVERSION",
        "sourceBranch": "BUILD_SOURCEBRANCH", "repositoryId": "BUILD_REPOSITORY_ID",
        "platformVersion": "PLATFORM_VERSION",
    }.items()}
