"""Guarded, non-destructive Fabric deployment with environment-specific bindings."""

import json
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .inventory import ENVIRONMENTS, contained, digest, guid, read_json, require, write_json
from .policy import request_payload, select_items, validate_review
from .release import verify

API = "https://api.fabric.microsoft.com/v1"


def validate_target(config, environment):
    require(environment in ENVIRONMENTS, "Unknown promotion environment")
    target = config["environments"][environment]
    workspace = guid(target["workspaceId"])
    # Unconfigured later stages don't block dev, but configured targets must differ.
    others = [v["workspaceId"].lower() for k, v in config["environments"].items() if k != environment]
    require(workspace not in others, "Dev, test and prod must use distinct workspaces")
    for dependency in config.get("externalDependencies", {}).values():
        external_workspace = guid(dependency["environments"][environment]["workspaceId"])
        others = [v["workspaceId"].lower() for k, v in dependency["environments"].items() if k != environment]
        require(external_workspace not in others, "External dev, test and prod workspaces must differ")
    if "SemanticModel" in config["allowedItemTypes"]:
        guid(target["semanticModelConnectionId"])
    return target


class FabricAPI:
    def __init__(self, credential):
        self.credential = credential

    def get(self, path):
        # Only relative API paths are accepted; pagination cannot redirect the token.
        require(path.startswith("/") and not path.startswith("//"), "Invalid Fabric API path")
        for attempt in range(5):
            token = self.credential.get_token("https://api.fabric.microsoft.com/.default").token
            request = urllib.request.Request(API + path, headers={"Authorization": "Bearer " + token})
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code not in {429, 500, 502, 503, 504} or attempt == 4:
                    raise
                delay = error.headers.get("Retry-After", str(2 ** attempt))
                time.sleep(min(int(delay) if delay.isdigit() else 2 ** attempt, 30))

    def items(self, workspace):
        path = f"/workspaces/{guid(workspace)}/items"
        result, continuation = [], None
        seen = set()
        while True:
            page = self.get(path + ("?continuationToken=" + urllib.parse.quote(continuation, safe="")
                                    if continuation else ""))
            result.extend(page["value"])
            continuation = page.get("continuationToken")
            if not continuation:
                return result
            require(continuation not in seen, "Repeated Fabric continuation token")
            seen.add(continuation)


def resolve_external(config, environment, api):
    resolved = {}
    for name, dependency in config.get("externalDependencies", {}).items():
        workspace = dependency["environments"][environment]["workspaceId"]
        matches = [i for i in api.items(workspace) if i["type"] == dependency["type"]
                   and i["displayName"] == dependency["itemName"]]
        require(len(matches) == 1, f"Missing or ambiguous external dependency: {name}")
        item = matches[0]
        lakehouse = api.get(f"/workspaces/{guid(workspace)}/lakehouses/{guid(item['id'])}")
        sql = lakehouse["properties"]["sqlEndpointProperties"]
        require(sql["provisioningStatus"] == "Success", f"External SQL endpoint not ready: {name}")
        endpoint = sql["connectionString"]
        require(re.fullmatch(r"[a-zA-Z0-9.-]+\.datawarehouse\.fabric\.microsoft\.com", endpoint),
                "Unexpected SQL endpoint format")
        resolved["external:" + name] = dict(workspaceId=workspace, itemId=item["id"], sqlEndpoint=endpoint)
    return resolved


def parameter_document(manifest, config, environment, external):
    items = {i["logicalId"]: i for i in manifest["items"]}
    rules = []
    for binding in manifest["bindings"]:
        item = items[binding["item"]]
        target = binding["target"]
        if target == "workspace":
            value = config["environments"][environment]["workspaceId"]
        elif target.startswith("item:"):
            dependency = items[target[5:]]
            value = f"$items.{dependency['type']}.{dependency['name']}.$id"
        else:
            value = external[target]["sqlEndpoint"]
        rules.append(dict(find_value=binding["find"], replace_value={environment: value},
                          item_type=item["type"], item_name=item["name"]))
    result = {"find_replace": rules} if rules else {}
    if "SemanticModel" in config["allowedItemTypes"]:
        result["semantic_model_binding"] = {"default": {"connection_id": {
            environment: config["environments"][environment]["semanticModelConnectionId"]}}}
    return result


def plan(manifest, remote):
    expected = {(i["type"], i["name"]) for i in manifest["items"]}
    existing = [(i["type"], i["displayName"]) for i in remote]
    require(len(existing) == len(set(existing)), "Ambiguous target item names")
    return dict(create=sorted(expected - set(existing)), update=sorted(expected & set(existing)),
                unmanagedRetained=sorted(set(existing) - expected), delete=[])


def deploy(release, environment, receipt, expected, credential=None, publisher=None,
           policy_review=None, policy_mode="passing", policy_digest=None):
    release, receipt = Path(release), Path(receipt)
    provenance = verify(release, expected)
    config = read_json(release / "config.json")
    manifest = read_json(release / "inventory/manifest.json")
    document = dict(schemaVersion=1, environment=environment,
                    workspaceId=config["environments"][environment]["workspaceId"],
                    provenance=provenance, releaseDigest=digest(release / "checksums.json"), status="started")
    if policy_review is not None:
        result = read_json(policy_review)
        reviews = validate_review(result, request_payload(release, environment), environment, policy_digest)
        graph = read_json(release / "inventory/dependencies.json")
        selected = select_items(manifest, graph, reviews, policy_mode)
        document.update(policyReviewId=result["decisionId"], policyDigest=result["policyDigest"],
                        policyMode=policy_mode, selectedItemIds=sorted(selected),
                        skippedItems=[dict(logicalId=i["logicalId"], name=i["name"],
                                           findings=reviews[i["logicalId"]]["findings"])
                                      for i in manifest["items"] if i["logicalId"] not in selected])
        manifest = dict(manifest, items=[i for i in manifest["items"] if i["logicalId"] in selected],
                        bindings=[b for b in manifest["bindings"] if b["item"] in selected],
                        deploymentOrder=[i for i in manifest["deploymentOrder"] if i in selected])
        needed_external = {e["dependency"][9:] for e in graph["edges"]
                           if e["item"] in selected and e["dependency"].startswith("external:")}
        config = dict(config, allowedItemTypes=sorted({i["type"] for i in manifest["items"]}),
                      externalDependencies={k: v for k, v in config.get("externalDependencies", {}).items()
                                            if k in needed_external})
        if not selected:
            document.update(status="skipped", items=[], externalDependencies={},
                            plan=dict(create=[], update=[], unmanagedRetained=[], delete=[]))
            write_json(receipt, document)
            return
    target = validate_target(config, environment)  # Before authentication or any mutation.
    if credential is None:
        from azure.identity import AzureCliCredential
        credential = AzureCliCredential()
    api = FabricAPI(credential)
    workspace = target["workspaceId"]
    api.get(f"/workspaces/{guid(workspace)}")
    external = resolve_external(config, environment, api)
    before = api.items(workspace)
    document.update(externalDependencies=external, plan=plan(manifest, before))
    write_json(receipt, document)
    try:
        with tempfile.TemporaryDirectory(prefix="fabric-promotion-") as directory:
            work = Path(directory).resolve() / "workspace"
            work.mkdir()
            # Only selected, verified files reach the publisher. Preserve relative paths
            # for report/model and notebook bindings without modifying the release.
            for item in manifest["items"]:
                for name in item["files"]:
                    destination = work / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(contained(release / "workspace", name), destination)
            # JSON is valid YAML, avoiding a second parser in the offline toolchain.
            write_json(work / "parameter.yml", parameter_document(manifest, config, environment, external))
            if publisher is None:
                from fabric_cicd import FabricWorkspace, publish_all_items
                publisher = lambda: publish_all_items(FabricWorkspace(
                    workspace_id=workspace, repository_directory=str(work), environment=environment,
                    item_type_in_scope=config["allowedItemTypes"], token_credential=credential))
            publisher()
        # Library waits for its operations; verify every managed item is visible and unique.
        after = api.items(workspace)
        deployed = []
        for item in manifest["items"]:
            matches = [r for r in after if r["type"] == item["type"] and r["displayName"] == item["name"]]
            require(len(matches) == 1, f"Post-deployment item verification failed: {item['name']}")
            deployed.append(dict(logicalId=item["logicalId"], physicalId=matches[0]["id"],
                                 type=item["type"], name=item["name"]))
        document.update(status="succeeded", items=deployed)
    except Exception:
        document["status"] = "failed"
        raise
    finally:
        write_json(receipt, document)
