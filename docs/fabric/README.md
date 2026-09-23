# Fabric workspace CI/CD

Fabric and Azure Functions share this repository, but have separate templates,
Python packages, dependencies, artifacts, tests and deployment targets.

| Workload | CI / CD templates | Python | Artifact |
| --- | --- | --- | --- |
| Azure Functions | `templates/azure-functions/python/{ci,cd}/` | `platform_azure_functions`, app runtime | `function-package` ZIP |
| Fabric items | `templates/fabric/{ci,cd}/` | `platform_fabric`, Python 3.12 | `fabric-release` directory |

Fabric templates never import or extend Function App templates. They never build
an application ZIP, configure app settings, invoke a function, or install app dependencies.

## Consumer contract

The initial consumers are `analytics-dev` and `data-engineering-dev` in
`example-fabric-project`. Each owns `.fabric/config.json`, CI/CD entry points, item
definitions, target IDs, governance defaults and external dependency declarations.
Use their `.azure-pipelines/{ci,cd}.yml` files as working consumers. For a new
repository, use the [Fabric starter](../../examples/fabric/README.md).

CI extends `templates/fabric/ci/stages.yml@platform` and declares the `platform`
repository resource. CD extends `templates/fabric/cd/stages.yml@platform`, declares
the same resource and a pipeline resource named **fabricCI** pointing to that
consumer's CI definition. Keep both platform refs identical; pin both to a tested
release tag when one exists. The templates default to `ubuntu-latest` and expose
`vmImage` for agents that can reach private targets. Python 3.12 is independent of
the Functions runtime. The Fabric runtime dependency set is pinned in
`requirements/fabric/runtime.txt` and copied into each CI artifact.

## Generated inventory and dependency graph

CI scans the configured `itemRoots` for `.platform` files, requiring unique
logical IDs and type/name pairs, required item definition files, valid JSON,
allowed types, and an owner and classification for every item. The root list is
an explicit management boundary: source outside it is not deployed. Add new
items under an existing root to include them automatically. Add a new root to
the configuration if its location changes. Local Power BI state and Git files
are excluded, and symlinks are rejected.

Each release contains:

- `workspace/`: only the managed item definitions, preserving relative paths.
- `inventory/manifest.json`: logical identity, paths, item types, per-file SHA-256
  hashes, effective governance, discovered bindings and deployment order.
- `inventory/dependencies.json`, `dependencies.mmd`, and `README.md`: a machine
  readable graph and Mermaid rendering. Arrows run from prerequisite to dependent.
- `config.json`, `provenance.json`: targets and repository/build/commit/platform
  revision. No credentials belong in these files.
- `tooling/platform_fabric/`: the exact CI-selected deployment code.
- `tooling/requirements.txt`: the pinned Fabric runtime dependencies, with
  `checksums.json` covering these and all other release files.

CI generates these outputs for main and PR builds without Fabric credentials.
It does not commit generated files back to Git. Inspect the CI artifact during
review. Local `.fabric/generated/` output is ignored and can be regenerated:

```bash
cd ../analytics-dev # or ../data-engineering-dev
PYTHONPATH=../platform-dev/python python3 -m platform_fabric inventory \
  --root . --output .fabric/generated
```

Supported static lineage covers report `datasetReference.byPath`, notebook
`# META` lakehouse bindings, literal TMDL `Sql.Database` sources, references to
known local logical IDs, and explicit `dependencies` declarations. Unknown
report/lakehouse/SQL dependencies, invalid governance and cycles fail CI. The
current extractors support Lakehouse, Notebook, SemanticModel and Report. Add
an extractor and tests before enabling another type or notebook dependency
format. The graph is not a full parser of arbitrary notebook code or M/DAX,
nor a column-level or live Fabric lineage catalog.

`governance` supplies defaults; `itemOverrides` maps logical IDs to overrides.
Classification defaults to `internal` pending an owner's review. These are
repository governance metadata, **not** automatically applied Fabric sensitivity
labels, Purview policies or workspace access controls. Owner strings identify
the responsible repository/team; they do not grant permissions.

## Binding and promotion behavior

The engineering notebooks currently contain physical lakehouse IDs that differ
from the lakehouse `.platform` logical ID. CI resolves their default lakehouse
by its exact local name, records the dependency, checks the source workspace,
and generates per-notebook parameter rules. At deployment, the pinned SDK
publishes the lakehouse first and substitutes its target ID and workspace ID.
No development binding is used as a fallback for test or production.

Analytics declares its external engineering lakehouse in `.fabric/config.json`.
Before publishing, CD looks up the exact lakehouse name in the configured
engineering workspace for the **same environment** and reads its ready SQL
endpoint. That endpoint replaces `__LAKEHOUSE_SQL_ENDPOINT__`. A separately
configured Fabric connection ID binds the semantic model's credentials. Report
byPath references are rebound by the SDK to the deployed semantic model.
Publish engineering before analytics in each environment. This validates the
dependency's existence/readiness; it does not enforce an engineering build
version or orchestrate another repository's release.

CD promotes one `fabric-release` through `Fabric_dev` → `Fabric_test` →
`Fabric_prod`. Each later stage requires its predecessor to have succeeded;
skipping a predecessor cannot authorize a higher environment. Each stage:

1. Checks the selected CI run using `System.AccessToken`: successful completion,
   allowed main branch, no PR reason, matching pipeline, repository and commit.
2. Downloads that run's artifact, verifies provenance and its exact file set and
   hashes, and regenerates the inventory to verify consistency.
3. Rejects unconfigured workspace/connection IDs, duplicate environment workspace
   targets and unresolved external dependencies before publishing.
4. Copies definitions into a temporary directory for parameterization and calls
   `fabric-cicd`. The original release remains unchanged.
5. Verifies every managed target item exists uniquely and publishes a receipt
   with release digest, provenance, workspace ID, logical-to-physical ID mapping,
   create/update plan, retained unmanaged items and deployment outcome.

The SDK handles Fabric operation completion. The postcheck verifies item presence,
not data quality, semantic model refresh, table availability or notebook execution.
No orphan deletion is called. Removed/renamed items remain in the workspace for
separately reviewed retirement; unmanaged items are listed in the receipt. Lakehouse
data is not promoted. A failed publish can leave partial changes; it blocks later
stages but is not an automatic rollback. Revert source and build a new release,
or rerun a matching-commit known-good CI release after reviewing compatibility.

## Per-artifact policy reviews and pipeline enforcement

The policy API returns the complete submitted release `manifest` and one result in
`items[]` for each logical ID. Passing and failing artifacts both remain in the
response. The service returns no overall deployment verdict and does not query the
live Fabric workspace. Azure Pipelines owns deployment enforcement.

To enable reviews, supply these CD template parameters and set the secret Azure
Pipelines variable `PolicyApiKey`:

```yaml
policyApiUrl: https://policy.example.internal
policyMode: passing
```

With `passing`, the pipeline deploys only items with `items[].approved: true`.
Failed prerequisites also fail their dependents; selection must be closed over
local dependencies. `all` is an optional pipeline mode that requires every item to
pass. An empty `policyApiUrl` preserves the existing flow without policy reviews.
Configure the policy service's registry and rules for the real targets before
activation, and create a new CI release containing the updated platform tooling.

The review step runs after release verification. It validates the returned manifest,
workspace, environment, request digest and exact item set. API failures, malformed
results and mismatches fail the pipeline without a full-release fallback. The deploy
step revalidates the review, copies only selected files into its temporary directory,
and scopes bindings, external lookups and target checks to selected artifacts.
The verified release stays immutable. Failed artifacts already in Fabric remain
unchanged; they are not deleted.

Both `policy.json` (complete manifest and reviews) and `deployment.json` are retained
in the stage receipt artifact. The deployment receipt records the review ID, policy
digest, selected IDs, skipped IDs and reasons. When no items pass, deployment writes
`status: skipped`, makes no Fabric calls, and completes successfully. Each environment
reviews the complete release independently, so stage success does not mean every
artifact was deployed in the preceding environment.

For local or custom pipeline integration, use `platform_fabric review --release ...
--environment ... --url ... --receipt ...`, then `platform_fabric deploy ...
--policy-review ... --policy-mode passing`. The review command validates release
provenance using the same `CI_*` variables as verification and deployment. Optional
`--policy-digest` pins a policy snapshot in either command. Receipts are trusted job
artifacts bound to the request, not signed deployment credentials.

## Activate when the workspaces are ready

1. Publish the platform changes before consumer YAML, since Azure DevOps loads
   templates from remote Git. No push, pipeline registration or deployment is
   performed by creating these files locally.
2. Set every dev/test/prod `workspaceId` in each consumer's `.fabric/config.json`.
   Set analytics' three external engineering workspace IDs and its three
   `semanticModelConnectionId` values. These are **Fabric connection GUIDs**,
   distinct from Azure DevOps service connection names. Configure the connections'
   credentials and SQL permissions in Fabric; never commit secrets.
3. Replace the three service connection names in each `.azure-pipelines/cd.yml`.
   Prefer Azure Resource Manager workload identity federation connections usable
   by `AzureCLI@2` in the Fabric tenant. Authorize only the required pipeline.
4. Enable the tenant settings needed for service principals to call Fabric APIs,
   grant the deployment identity the required workspace/item permissions (normally
   Contributor on deployment workspaces), and grant the analytics identity read
   access to its external engineering lakehouse and use access to its Fabric SQL
   connections. Check each item type's service-principal support. The signed-in
   Azure CLI identity provides the Fabric credential; no interactive login is used.
5. Create `<repo>-ci` and `<repo>-cd` definitions at `.azure-pipelines/ci.yml`
   and `.azure-pipelines/cd.yml` in the same repository/project. CD defaults to
   `refs/heads/main`. Grant Build Service read access to `platform-dev`, authorize
   repository and `fabricCI` resources, and allow CI build/artifact reads. For
   Azure Repos, set a **main build-validation branch policy**; YAML `pr` is not
   an Azure Repos PR policy.
6. Precreate the three named Azure DevOps environments from each CD file. On
   **test and prod**, configure required approvals and a branch control check for
   protected `refs/heads/main`. Set an **exclusive lock** on each environment;
   YAML uses sequential lock behavior. Restrict environment/service-connection
   administration and pipeline editing. Approvals and checks live in Azure
   DevOps, not YAML: these templates do not create or prove their existence.
7. Disable old analytics definitions pointing at `.azure-pipelines/test.yml` or
   the removed direct deployment script. Run CI first, inspect its inventory,
   deploy engineering, then analytics. Add representative data/refresh acceptance
   checks before approving production.

Main CI completion starts CD automatically once registered and authorized. Keep
CD unregistered or disabled until approvals and configuration are ready. Manual
CD runs must select a CI build whose commit matches the CD run's source revision.
Artifact retention must cover the intended audit and rollback window. SHA-256
checks detect mutation; they are not signatures. Trust is rooted in protected
source, successful CI and Azure DevOps artifact/resource permissions.

## Validation and references

`python -m pytest tests/fabric/test_fabric.py` exercises offline discovery, failure gates,
release integrity and the actual CI-run verification script embedded in YAML.
With Fabric dependencies installed under Python 3.12, run
`PYTHONPATH=python python tests/fabric/fabric_sdk_smoke.py` for SDK parameter/rebinding
contracts without contacting Fabric. The platform pipeline runs this in its
own job, independently of Functions dependencies and runtime.

- [Microsoft fabric-cicd parameterization](https://microsoft.github.io/fabric-cicd/latest/how_to/parameterization/)
- [Microsoft fabric-cicd code reference](https://microsoft.github.io/fabric-cicd/latest/reference/code_reference/)
- [Fabric lakehouse properties API](https://learn.microsoft.com/en-us/rest/api/fabric/lakehouse/items/get-lakehouse)
- [Azure DevOps environment approvals and checks](https://learn.microsoft.com/en-us/azure/devops/pipelines/process/approvals?view=azure-devops)
