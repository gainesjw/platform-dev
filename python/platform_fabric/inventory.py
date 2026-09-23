"""Deterministic, offline inventory of the explicitly managed Fabric item roots."""

import hashlib
import json
import re
from pathlib import Path
from uuid import UUID

ENVIRONMENTS = ("dev", "test", "prod")
SUPPORTED = {"Lakehouse", "Notebook", "SemanticModel", "Report"}
IGNORED = {".git", ".pbi", ".DS_Store", "__pycache__", ".venv"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def contained(root, relative):
    root = Path(root).resolve()
    path = root / relative
    require(not Path(relative).is_absolute() and ".." not in Path(relative).parts,
            f"Unsafe relative path: {relative}")
    require(path.resolve().is_relative_to(root), f"Path escapes root: {relative}")
    return path


def files(root):
    result = []
    for path in sorted(Path(root).rglob("*")):
        if any(part in IGNORED for part in path.relative_to(root).parts):
            continue
        require(not path.is_symlink(), f"Symlinks are not allowed: {path}")
        if path.is_file():
            result.append(path)
    return result


def guid(value):
    return str(UUID(value))


def notebook_metadata(text):
    # Fabric exports multiple independent META JSON blocks, one per cell.
    blocks = re.findall(r"(?:^# META .*\n?)+", text, re.MULTILINE)
    return [json.loads("\n".join(line[7:] for line in b.splitlines())) for b in blocks]


def topological_order(ids, edges):
    pending = {key: set() for key in ids}
    for edge in edges:
        if edge["dependency"] in pending:
            pending[edge["item"]].add(edge["dependency"])
    result = []
    while pending:
        ready = sorted(key for key, deps in pending.items() if not deps)
        require(ready, "Dependency cycle detected")
        result.extend(ready)
        for key in ready:
            del pending[key]
        for deps in pending.values():
            deps.difference_update(ready)
    return result


def generate(root, config):
    root = Path(root).resolve()
    require(config.get("schemaVersion") == 1, "Unsupported configuration schema")
    require(set(config["environments"]) == set(ENVIRONMENTS), "Configure dev, test and prod")
    allowed = set(config["allowedItemTypes"])
    require(allowed and allowed <= SUPPORTED, "Unsupported managed item type")
    platforms = set()
    for relative in config["itemRoots"]:
        directory = contained(root, relative)
        require(directory.is_dir(), f"Missing item root: {relative}")
        for path in files(directory):
            if path.name == ".platform":
                platforms.add(path)
        # Fail for broken item folders, rather than silently dropping an item.
        for directory in [directory, *directory.rglob("*")]:
            if directory.is_dir() and directory.suffix[1:] in SUPPORTED:
                require((directory / ".platform").is_file(), f"Missing .platform: {directory}")
    require(platforms, "No managed Fabric items discovered")
    items, contents, paths = {}, {}, {}
    names = set()
    for platform in sorted(platforms):
        metadata = read_json(platform)
        kind, name = metadata["metadata"]["type"], metadata["metadata"]["displayName"]
        key = guid(metadata["config"]["logicalId"])
        require(kind in allowed, f"Item type outside governance scope: {kind}")
        require(name and key not in items and (kind, name) not in names, "Duplicate item identity/name")
        require(platform.parent.suffix == "." + kind, f"Item folder/type mismatch: {platform}")
        names.add((kind, name))
        relative = platform.parent.relative_to(root).as_posix()
        governance = dict(config["governance"])
        governance.update(config.get("itemOverrides", {}).get(key, {}))
        require(governance.get("owner") and governance.get("classification") in
                {"public", "internal", "confidential", "restricted"}, f"Missing governance for {name}")
        item_files = files(platform.parent)
        file_hashes = {p.relative_to(root).as_posix(): digest(p) for p in item_files}
        for path in item_files:
            if path.suffix == ".json" or path.name in {".platform", "definition.pbir", "definition.pbism"}:
                read_json(path)
        required = {"Notebook": "notebook-content.py", "Lakehouse": "lakehouse.metadata.json",
                    "Report": "definition.pbir", "SemanticModel": "definition.pbism"}[kind]
        require((platform.parent / required).is_file(), f"Missing {required}: {name}")
        shortcuts = platform.parent / "shortcuts.metadata.json"
        if kind == "Lakehouse" and shortcuts.exists():
            require(read_json(shortcuts) == [], "Add shortcut dependency extraction and publishing before managing shortcuts")
        items[key] = dict(logicalId=key, type=kind, name=name, path=relative,
                          governance=governance, files=file_hashes)
        contents[key] = "\n".join(p.read_text(encoding="utf-8-sig") for p in item_files
                                    if p.suffix in {".py", ".tmdl", ".json", ".pbir"})
        paths[platform.parent.resolve()] = key
    require(set(config.get("itemOverrides", {})) <= set(items), "Override refers to missing item")
    external = config.get("externalDependencies", {})
    for name, dependency in external.items():
        require(dependency.get("owner") and dependency.get("repository"), f"Missing external owner: {name}")
        require(dependency["type"] == "Lakehouse", "Only external Lakehouse bindings are supported")
        require(set(dependency["environments"]) == set(ENVIRONMENTS), f"Missing external environments: {name}")
    edges, bindings = [], []

    def edge(item, dependency, evidence):
        require(dependency in items or dependency.startswith("external:") and dependency[9:] in external,
                f"Unresolved dependency: {dependency}")
        edges.append(dict(item=item, dependency=dependency, evidence=evidence))

    for key, item in items.items():
        directory = root / item["path"]
        if item["type"] == "Report":
            reference = read_json(directory / "definition.pbir")["datasetReference"]
            require("byPath" in reference, "Managed reports must use a local semantic model byPath")
            target = (directory / reference["byPath"]["path"]).resolve()
            require(target in paths and items[paths[target]]["type"] == "SemanticModel",
                    f"Unresolved report model: {item['name']}")
            edge(key, paths[target], "definition.pbir:datasetReference.byPath")
        elif item["type"] == "Notebook":
            for block in notebook_metadata((directory / "notebook-content.py").read_text()):
                deps = block.get("dependencies", {})
                require(set(deps) <= {"lakehouse"}, "Add a dependency extractor for this notebook dependency")
                lake = deps.get("lakehouse", {})
                if not lake:
                    continue
                name = lake.get("default_lakehouse_name")
                candidates = [i for i, v in items.items() if v["type"] == "Lakehouse" and v["name"] == name]
                require(len(candidates) == 1, f"Unresolved notebook lakehouse: {name}")
                target = candidates[0]
                source_id = lake["default_lakehouse"]
                source_workspace = lake["default_lakehouse_workspace_id"]
                guid(source_id)
                guid(source_workspace)
                require(source_workspace == config.get("sourceWorkspaceId"), "Unexpected source workspace in notebook")
                require(all(x["id"] == source_id for x in lake.get("known_lakehouses", [])),
                        "Additional notebook lakehouses require an explicit dependency extractor")
                edge(key, target, "notebook META default_lakehouse_name")
                bindings.extend([
                    dict(item=key, find=source_id, target="item:" + target),
                    dict(item=key, find=source_workspace, target="workspace"),
                ])
        elif item["type"] == "SemanticModel":
            # M expressions are not a general-purpose lineage language. Require an
            # explicit external declaration for every supported Sql.Database source.
            sources = re.findall(r'Sql\.Database\(\s*"([^"]+)"\s*,\s*"([^"]+)"', contents[key])
            require(sources, f"No supported Sql.Database source in {item['name']}; extend the extractor")
            for endpoint, database in sources:
                matches = [(n, d) for n, d in external.items() if d["sourceToken"] == endpoint
                           and d["itemName"] == database]
                require(len(matches) == 1, f"Undeclared SQL source: {endpoint}/{database}")
                target = "external:" + matches[0][0]
                edge(key, target, "TMDL Sql.Database")
                bindings.append(dict(item=key, find=endpoint, target=target))
        # Known local logical IDs also contribute lineage, excluding own identity.
        for target in items:
            if target != key and target in contents[key]:
                edge(key, target, "logical ID reference")
    for declaration in config.get("dependencies", []):
        require(declaration["item"] in items, "Explicit dependency refers to missing item")
        edge(declaration["item"], declaration["dependency"], "explicit declaration")
    # The pinned publisher processes these types in this order. Reject graphs
    # that it cannot safely honor instead of presenting a misleading plan.
    rank = {"Lakehouse": 0, "Notebook": 1, "SemanticModel": 2, "Report": 3}
    topological_order(items, edges)
    for dependency in edges:
        if dependency["dependency"] in items:
            require(rank[items[dependency["dependency"]]["type"]] < rank[items[dependency["item"]]["type"]],
                    "Dependency is incompatible with the supported Fabric publish order")
    edges = sorted({json.dumps(e, sort_keys=True): e for e in edges}.values(),
                   key=lambda e: (e["item"], e["dependency"], e["evidence"]))
    order = topological_order(items, edges)
    manifest = dict(schemaVersion=1, repository=config["repository"], items=list(items.values()),
                    externalDependencies=external, bindings=bindings, deploymentOrder=order,
                    dependencyCoverage="Report byPath, notebook META lakehouse, TMDL Sql.Database, local logical IDs and explicit declarations")
    graph = dict(schemaVersion=1, nodes=[dict(id=k, label=v["type"] + ": " + v["name"], external=False)
                                      for k, v in items.items()] +
                 [dict(id="external:" + k, label=v["repository"] + "/" + v["itemName"], external=True)
                  for k, v in external.items()], edges=edges, deploymentOrder=order)
    return manifest, graph


def write_inventory(output, manifest, graph):
    output = Path(output)
    write_json(output / "manifest.json", manifest)
    write_json(output / "dependencies.json", graph)
    node_ids = {n["id"]: "n" + str(i) for i, n in enumerate(graph["nodes"])}
    lines = ["flowchart LR"]
    for node in graph["nodes"]:
        label = node["label"].replace('"', "'").replace("<", "").replace(">", "")
        lines.append(f'  {node_ids[node["id"]]}["{label}"]')
    for edge in graph["edges"]:
        lines.append(f'  {node_ids[edge["dependency"]]} --> {node_ids[edge["item"]]}')
    (output / "dependencies.mmd").write_text("\n".join(lines) + "\n")
    table = ["| Type | Name | Owner | Classification | Logical ID |",
             "| --- | --- | --- | --- | --- |"]
    for item in manifest["items"]:
        values = [item["type"], item["name"], item["governance"]["owner"],
                  item["governance"]["classification"], item["logicalId"]]
        table.append("| " + " | ".join(str(v).replace("|", "\\|").replace("\n", " ") for v in values) + " |")
    (output / "README.md").write_text(
        "# Generated Fabric inventory\n\n" + "\n".join(table) +
        "\n\nArrows point from prerequisite to dependent item.\n\n```mermaid\n"
        + "\n".join(lines) + "\n```\n\n" + manifest["dependencyCoverage"] +
        ". This is static deployment lineage, not complete runtime or column lineage.\n")
