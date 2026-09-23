"""Offline contract check against the pinned SDK. Run in the Fabric Python venv."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from azure.core.credentials import AccessToken
from fabric_cicd import FabricWorkspace, disable_file_logging
from fabric_cicd._items._report import func_process_file

from platform_fabric.deploy import parameter_document
from platform_fabric.inventory import generate, write_json


class OfflineCredential:
    def get_token(self, *scopes, **kwargs):
        return AccessToken("offline-test-token", 4102444800)


def main():
    disable_file_logging()
    with tempfile.TemporaryDirectory() as directory, patch(
        "requests.sessions.Session.request", side_effect=AssertionError("SDK smoke must remain offline")
    ):
        root = Path(directory).resolve()
        target_workspace, source_workspace, source_lake, target_lake, target_model = [str(uuid4()) for _ in range(5)]
        for kind, name in [("Lakehouse", "lake"), ("Notebook", "ingest"), ("SemanticModel", "model"), ("Report", "report")]:
            folder = root / "items" / (name + "." + kind)
            write_json(folder / ".platform", dict(metadata=dict(type=kind, displayName=name),
                       config=dict(version="2.0", logicalId=str(uuid4()))))
            if kind == "Lakehouse":
                write_json(folder / "lakehouse.metadata.json", {"defaultSchema": "dbo"})
            elif kind == "Notebook":
                meta = dict(dependencies=dict(lakehouse=dict(default_lakehouse=source_lake,
                            default_lakehouse_name="lake", default_lakehouse_workspace_id=source_workspace,
                            known_lakehouses=[dict(id=source_lake)])))
                (folder / "notebook-content.py").write_text("\n".join("# META " + s for s in json.dumps(meta, indent=2).splitlines()) + "\n")
            elif kind == "SemanticModel":
                write_json(folder / "definition.pbism", {"version": "4.0"})
                (folder / "model.tmdl").write_text('Source = Sql.Database("__ENDPOINT__", "lake")')
            else:
                write_json(folder / "definition.pbir", {"datasetReference": {"byPath": {"path": "../model.SemanticModel"}}})
        config = dict(schemaVersion=1, repository="fixture", itemRoots=["items"],
            allowedItemTypes=["Lakehouse", "Notebook", "SemanticModel", "Report"],
            sourceWorkspaceId=source_workspace, governance=dict(owner="fixture", classification="internal"),
            environments={e: dict(workspaceId=target_workspace, semanticModelConnectionId=str(uuid4())) for e in ["dev", "test", "prod"]},
            externalDependencies={"source": dict(repository="engineering", owner="engineering", type="Lakehouse",
                itemName="lake", sourceToken="__ENDPOINT__", environments={e: dict(workspaceId=str(uuid4())) for e in ["dev", "test", "prod"]})})
        manifest, _ = generate(root, config)
        endpoint = "example.datawarehouse.fabric.microsoft.com"
        write_json(root / "parameter.yml", parameter_document(manifest, config, "test", {"external:source": {"sqlEndpoint": endpoint}}))
        workspace = FabricWorkspace(workspace_id=target_workspace, repository_directory=str(root),
            environment="test", item_type_in_scope=config["allowedItemTypes"], token_credential=OfflineCredential())
        workspace._refresh_repository_items()
        assert sum(len(v) for v in workspace.repository_items.values()) == 4
        workspace.workspace_items = {"Lakehouse": {"lake": {"id": target_lake}}}
        # Dynamic $items resolution refreshes remote metadata. Supply the known
        # target inventory while retaining the SDK's actual substitution logic.
        workspace._refresh_deployed_items = lambda: None
        for kind, name in [("Notebook", "ingest"), ("SemanticModel", "model")]:
            item = workspace.repository_items[kind][name]
            for file in item.item_files:
                if file.name == ".platform":
                    continue
                changed = workspace._replace_parameters(file, item)
                if kind == "Notebook":
                    assert source_lake not in changed and source_workspace not in changed
                    assert target_lake in changed and target_workspace in changed
                elif file.name == "model.tmdl":
                    assert "__ENDPOINT__" not in changed and endpoint in changed
        model = workspace.repository_items["SemanticModel"]["model"]
        model.guid = target_model
        report = workspace.repository_items["Report"]["report"]
        definition = next(f for f in report.item_files if f.name == "definition.pbir")
        rendered = workspace._replace_logical_ids(func_process_file(workspace, report, definition))
        assert target_model in rendered and "byPath" not in rendered
        assert workspace.environment_parameter["semantic_model_binding"]["default"]["connection_id"]["test"]
        print("Pinned SDK accepted generated parameters, rebound notebooks/SQL, and linked report to model")


if __name__ == "__main__":
    main()
