# Platform validation and Docker testing

[Repository README](../../../README.md)

Run these commands from the repository root.

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements/azure-functions/python/test.txt
.venv/bin/python -m pytest
```

No Azure subscription resources, service connection, storage account or deployed
Function App are needed for these tests. Dependency installation requires package
index access. After installation, the local tests do not call Azure.

The local suite includes:

- Shared helper unit tests with mocked Azure responses: runtime compatibility,
  optional capabilities, parsing, polling, function matching and secret redaction.
- YAML parsing and structural contracts for starter parameters, opt-in deployment,
  branch/PR/success guards, required reports, artifact wiring and hook ordering.
  These are regression checks, not a replacement for Azure's YAML compiler.
- A real Python Function App fixture whose HTTP handler and indexing are exercised
  without a running Functions host. Tests execute the template's actual validation
  Bash against good packages, missing imports, empty apps and syntax errors.
- A Linux-only test of the template's actual GNU copy command, including nested
  paths, excluded local settings and missing files. This test skips on macOS.

Register `.azure-pipelines/azure-pipelines.yml` as this repo's Azure DevOps
validation pipeline and make it a required main-branch build-validation policy.
Adding YAML alone does not register the pipeline or configure branch protection.
The Functions portion uses Linux and Python 3.14 and runs four stages. Fabric
has a separate Python 3.12 validation stage; see [platform validation](../../testing.md).

1. `AzureFunctionsTests` runs the Functions suite and shared contracts, publishing JUnit results.
2. `Build` includes the shared CI component from the candidate checkout, with no
   CD component or deployment inputs. Its test command stages the fixture as a normal app in
   the fresh checkout, then exercises dependency installation, test/coverage
   publishing, the default package allowlist, a validation hook, indexing,
   compilation, archiving and artifact publication.
3. `InspectArtifact` downloads the current run's ZIP, checks its root layout and
   exclusions, and imports/indexes it with agent site-packages disabled so that
   dependencies must come from the artifact.
4. `ContainerSmoke` downloads the same ZIP and mounts its extracted contents into
   Microsoft's `mcr.microsoft.com/azure-functions/python:4-python3.14` image. It
   starts the real Functions host, polls `/api/health` for up to 180 seconds and
   requires HTTP 200 with the expected fixture response. Failures fail the stage.
   JUnit results, host logs and container/image metadata are published for diagnosis.

The container test runs on the hosted Ubuntu agent and requires Docker, access to
Microsoft's public container registry and package-index access. No image is pushed,
no Azure resources are created, and no service connection is used. The HTTP-only
fixture uses file-based host secrets and does not need Azurite or cloud storage.
Dependencies are taken from the Linux ZIP; the test does not reinstall or rebuild
the app inside the container. The container binds only to a dynamic localhost port
and is removed after success or failure. Pulls have a 10-minute timeout, readiness
has a 3-minute timeout, and the job has a 20-minute timeout.

The image uses a floating Python 3.14 runtime tag so CI detects upstream host
changes. The resolved image metadata is saved with each run. Update the image and
build Python version together; the contract suite checks they match. Microsoft's
[Functions image catalog](https://mcr.microsoft.com/en-us/artifact/mar/azure-functions/python/tags)
lists available versions. This test exercises Linux AMD64, matching the hosted
build; local ARM machines need Docker emulation and the Linux-built artifact.

To rerun the container test locally, download `function-app.zip` from the pipeline,
start Docker and use the existing test environment:

```bash
PACKAGE_ZIP=/absolute/path/to/function-app.zip \
FUNCTIONS_TEST_IMAGE=mcr.microsoft.com/azure-functions/python:4-python3.14 \
.venv/bin/python -m pytest tests/azure_functions/python/container_smoke.py -v --junitxml=test-results/container.xml
```

Ordinary `pytest` runs only the Docker harness's unit tests; the real container
test is selected explicitly by CI. Missing Docker fails that explicit test.

Run `tests/azure_functions/python/prepare_smoke_app.py` only in a disposable directory. It refuses to
overwrite app files; local tests stage it in temporary directories. The fixture
under `tests/azure_functions/python/fixtures/function_app` is test-only and is not a deployed application.

This validates Azure template expansion and build execution when the pipeline
runs in Azure DevOps; local pytest alone cannot prove those behaviors. It does
not yet test cross-repository authorization, optional platform-repo checkout,
deployment task execution or pre/post-deployment hooks. The container runs a real
Functions host but does not reproduce managed Azure hosting, identity or networking.
Structural deployment checks do not prove runtime deployment behavior.

### Adding deployment coverage later

Keep this credential-free validation pipeline as the required PR check. Once
infrastructure is available, add a separate consumer/sandbox pipeline using the
same fixture and the exact candidate platform revision. Exercise shared Python
checkout and `@self` hooks from that consumer repository. Deploy only to dedicated
nonproduction targets, retaining the template's deployment guards; check host
readiness and invoke `/api/health`, expecting `platform template smoke test`.
Add Flex/non-Flex targets and Python versions only as they become supported test
environments. Require successful sandbox validation before publishing immutable
release tags, and upgrade consumers through PRs that change their pinned tag.
Schedule repeat runs to detect agent, dependency and Azure service drift.

Checkout behavior follows [Microsoft's multi-repo checkout guidance](https://learn.microsoft.com/en-us/azure/devops/pipelines/repos/multi-repo-checkout?view=azure-devops#workspace-repository).

See also [release and rollout guidance](releasing.md).
