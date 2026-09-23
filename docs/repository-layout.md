# Repository layout and new workload checklist

[`catalog.json`](../catalog.json) is the machine-readable index of supported
workloads, entry points, examples, documentation, test folders, helper packages,
runtime versions and artifact names. It is a discovery/validation index, not a
runtime loader; consumers continue to reference explicit YAML paths.

```text
platform-dev/
  catalog.json
  .azure-pipelines/
    azure-pipelines.yml                # fixed platform-dev-validation entry point
    validation/<workload>.yml           # private workload validation composition
  templates/
    <workload>[/<runtime>]/
      ci/stages.yml
      cd/stages.yml
      ci-cd.yml                        # optional combined entry point
  examples/<workload>[/<runtime>]/       # ci.yml, cd.yml, consumer configuration
  docs/
    repository-layout.md               # shared conventions
    consuming-pipelines.md             # onboarding across workloads
    template-reference.md              # entry point index
    testing.md                         # validation commands and boundaries
    releasing.md                       # versioning and consumer rollout
    <workload>[/<runtime>]/             # workload-specific guides
  python/<workload_package>/            # independent helper package
  requirements/
    shared/test.txt                    # common test tools only
    <workload>[/<runtime>]/test.txt      # workload validation environment
    <workload>[/<runtime>]/runtime.txt   # deployment tooling, when needed
  tests/
    contracts/                         # catalog and cross-workload contracts
    azure_functions/python/            # Functions tests, harness and fixtures
    fabric/                            # Fabric tests and SDK contract checks
  pytest.ini
```

Use lowercase kebab-case for YAML/docs/example workload paths, and snake_case
for Python packages and Python test directories. Add a runtime variant only when
it is part of the consumer workload contract, such as Python versus Node Function
Apps. Fabric deploys item definitions, so its Python tooling version is recorded
in the catalog without introducing a runtime variant in its public template path.

Azure Functions uses `platform_azure_functions`; Fabric uses `platform_fabric`.
Workload helpers use `platform_<workload>`; do not add unrelated workload code
to either existing package. Put platform dependencies under `requirements/`,
following the same workload boundaries. See [dependency file conventions](../requirements/README.md).
Consumer application requirements remain in their own repositories. Shared test
requirements must not become deployment requirements.

## Add a consumer of an existing workload

Copy the appropriate starter from `examples/`. The consumer owns triggers,
project naming, source/item roots, governance, target configuration and any
application-specific checks. Reuse platform behavior through a pinned repository
resource. Do not copy reusable stage implementations into application repositories.

## Add a new workload family

1. Add independent CI and CD entry points following the paths above. Use
   `stages.yml` for each public entry point and descriptive adjacent filenames
   for internal templates. Keep internal paths relative to their family.
2. Define a workload-specific artifact contract. CI validates and packages;
   CD verifies and deploys that artifact. Give artifacts and deployment stages
   distinct names so future pipelines can compose families without collisions.
3. Add an independent helper package only if needed; keep its credentials,
   deployment dependencies and runtime separate from other workloads. Share a
   cross-workload utility only after there is a concrete common requirement,
   with a neutral documented contract and tests.
4. Supply CI/CD starters, configuration examples and a workload guide. Document
   runtime versions, resource permissions, registration, approval setup,
   supported item types, rollback limits and what remains externally provisioned.
5. Add family tests/fixtures plus a matching-runtime job to platform validation.
   Add its private stage template under `.azure-pipelines/validation/` and reference
   it from the fixed `.azure-pipelines/azure-pipelines.yml` entry point. Do not move
   or rename that entry point: it runs the registered `platform-dev-validation` pipeline.
   Use `tests/contracts/` only for rules that apply across workloads. Integration
   tests must target dedicated sandboxes and are separate from offline PR checks.
6. Register the family in `catalog.json` and update the README. Catalog tests
   reject missing entry points, starter files or supporting directories.
7. Validate the candidate templates in Azure DevOps before tagging a release.
   Keep existing public paths/parameters compatible or introduce a new versioned
   path. Moving an internal test or guide is not permission to break consumers.

Do not pre-create empty template families or generic deployment hooks without a
consumer requirement. The structure accommodates future projects without mixing
their deployment semantics into the current Functions or Fabric implementations.

This standardization intentionally moves older public paths and helper imports.
The local consumers have been updated; see [migration and rollout](structure-migration.md).
