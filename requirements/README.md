# Dependency files

Platform-owned Python dependencies live here, grouped by workload and purpose.
Versions are pinned; a move between folders is not a dependency upgrade.

| File | Purpose | Python |
| --- | --- | --- |
| `shared/test.txt` | Common pytest, coverage and YAML test tools | 3.12 / 3.14 |
| `azure-functions/python/smoke-runtime.txt` | Dependencies of the platform's synthetic Function App fixture | 3.14 |
| `azure-functions/python/test.txt` | Common tests plus the Function App fixture runtime | 3.14 |
| `fabric/runtime.txt` | Fabric deployment SDK and its pinned dependency set | 3.12 |
| `fabric/test.txt` | Common tests plus the Fabric deployment SDK | 3.12 |

Install only the selected workload's `test.txt` in its validation environment.
The shared file contains no deployment SDKs. `-r` paths resolve relative to the
containing requirements file. Runtime files are flat, self-contained pin lists
so they can be copied into an artifact without external include paths.

The Function App fixture preparation script copies `smoke-runtime.txt` into the
temporary app as `requirements.txt`. The Fabric release builder copies
`fabric/runtime.txt` into `tooling/requirements.txt`, covered by release checksums.
CD installs from that exact artifact. No test dependencies enter a Fabric release.

The Azure Functions deployment helpers use the Python standard library and Azure
CLI; they need no separate Python runtime requirements file. The smoke app's
dependencies are not production application dependencies.

Consumer applications, including `data-acquisition`, retain their own
`requirements.txt` and `requirements-dev.txt`. Those files belong to their
application and remain the default inputs to the reusable Function App templates.
Fabric consumers use the SDK requirements captured by platform CI; notebook
execution environments and data libraries are outside this deployment SDK list.

The former platform root `requirements-dev.txt`, `tests/requirements.txt`, and
package-local requirements locations were replaced by this layout. Use
`python -m pip install -r requirements/<workload>/test.txt` from the repository
root; see [validation commands](../docs/testing.md).

For a future workload, add `requirements/<workload>[/<runtime>]/test.txt` and a
`runtime.txt` only when needed. Register their paths in `catalog.json`. Share test
tools through `shared/test.txt`; do not include another workload's runtime.
