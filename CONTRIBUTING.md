# Contributing to KubeTrail

Thanks for your help. This file tells you how to run the app for development, run the tests, and add quests and labs.

## Set up for development

Do the [Quickstart](README.md#quickstart) one time. Then start the server yourself with `--reload`, so it restarts when you change the code:

```sh
.venv/bin/uvicorn backend.main:app --reload
```

## Run the tests

```sh
.venv/bin/pytest
```

The tests do not need a running minikube. They replace the `kubectl` and `minikube` calls with fakes.
CI runs the same tests on macOS for each pull request (`.github/workflows/test.yml`).

The end-to-end test runs the machine solution of each lab (`tests/e2e/solutions/<id>.yaml`) against a real minikube:
Start lab, the solution steps, Check my work (all checks must pass), Reset. It skips a lab with a need that is not met.

```sh
.venv/bin/pytest -m e2e
```

It uses the current kubectl context, and it refuses a context that is not a minikube profile.
Run it before a lab merges. The recorded tool output for the unit tests is in `tests/fixtures/` (see its README).

## Project layout

| Path | What it holds |
| --- | --- |
| `backend/` | The FastAPI app: the API, the cluster guard, the lab runner and the progress file. |
| `frontend/` | The page. Plain ES modules and CSS, with no build step. |
| `content/` | The acts and quests. `content/index.yaml` lists the act files and gives their format. |
| `labs/` | One YAML file for each lab. |
| `scripts/doctor.py` | The setup checks that `./run.sh` runs. |
| `docs/designs/course-expansion.md` | The design, and the catalog of record for each quest and lab. |
| `ROADMAP.md` | The work after this design. |

## Rules

Each rule has its reason.

- **Write all text in ASD-STE100.** Many learners do not have English as a first language.
- **Quest ids never change.** `progress.json` keeps the done quests by id.
- **A lab states an end state and gives no command to copy.** The learner learns by finding the command. One exception: text that limits the blast radius (for example the `config_context` line of a Terraform backend) is given word for word.
- **Labs use GA APIs only.** An `alpha` or `beta` API can go away in a minor release.
- **Helm checks select the release Secret by label, with `status=deployed`, and never name it.** The name holds the revision number. Without `status=deployed`, the selector finds each revision.
- **A Helm lab has an empty `setup`.** The app stamps setup objects with its own `managed-by` label. Helm refuses to install over an object with a different `managed-by` value.
- **Terraform checks name the state Secret `tfstate-<workspace>-<lab-id>`.** The name is stable, and a named check turns on the wrong-namespace help.
- **Checks read EndpointSlices, not Endpoints.** The Endpoints API is deprecated.
- **Each lab has a machine solution in `tests/e2e/solutions/`.** The end-to-end test proves that the checks can pass.
- **Each lab pull request updates the entry of the lab in `docs/designs/course-expansion.md`.** That document is the catalog of record.
- **A lab that changes a chart works on a copy in `workspace/`.** The work of the learner never changes `charts/`. Git ignores `workspace/`, except `versions.tf` and `providers.tf`.
- **Each check has a `why`** that says why the end state matters. It never gives the fix. The page shows it only when the check fails.

## Add a quest

Add the quest to an act file in `content/`. The format of the act files is at the top of `content/index.yaml`.
`backend/content.py` validates the files and refuses unknown keys.

A READ quest needs nothing more. A LAB or BOSS quest also needs a lab file with the same id. See the next section.

A LAB quest describes the result to make, not the commands to type. For example, write "Make a Pod with the name hello and the label app=hello", not the `kubectl run` line.
Tell the learner what to look at, such as the Events in `describe`.
Only a READ quest can have the `code` field. Put the syntax of a lab in the `hints` of the lab. The page shows the hints one at a time.

## Add a lab

A lab is a YAML file in the `labs/` directory. The file name is the lab id.
For example, `labs/k3.yaml` has the id `k3`.

### The format of a lab file

```yaml
id: k3
title: Roll a Deployment and undo a bad rollout
namespace: lab-k3
setup: []
checks:
  - id: deployment-ready
    say: The Deployment "web" has 3 ready replicas.
    get: deployment/web
    path: "{.status.readyReplicas}"
    equals: "3"
hints:
  - Use `kubectl create deployment` with the --replicas flag.
```

A lab file has these keys:

| Key | Required | Description |
| --- | --- | --- |
| `id` | Yes | The lab id. It must be equal to the file name without `.yaml`. |
| `title` | Yes | The title of the lab. |
| `namespace` | Yes | The namespace of the lab. It must be a DNS label that starts with `lab-`. |
| `setup` | No | A list of Kubernetes objects. Start lab applies these objects in the lab namespace. |
| `checks` | Yes | A list of one or more checks. |
| `hints` | No | A list of texts. Put a command in backticks to show it as code. |

A check has these keys:

| Key | Required | Description |
| --- | --- | --- |
| `id` | Yes | The check id. Each check in a lab must have a different id. |
| `say` | Yes | The text that the page shows for the check. |
| `get` | Yes | The object to read, as `kind` or `kind/name`. For example, `deployment/web`. |
| `path` | Yes | One kubectl jsonpath expression in braces. For example, `{.spec.replicas}`. |
| `selector` | No | A label selector. Use it only when `get` has no name. |

A check must also have exactly one operator:

| Operator | The check passes when |
| --- | --- |
| `equals` | The value is equal to the given text. |
| `matches` | The full value matches the given regular expression. |
| `atLeast` | The value is a number that is equal to or more than the given number. |
| `atMost` | The value is a number that is equal to or less than the given number. |
| `exists` | `true`: the value exists and is not empty. `false`: the value does not exist. |

When `get` has no name, kubectl can give more than one value. The check passes only if each value passes.

### The rules for setup objects

The app validates each lab file strictly. These rules apply to the `setup` list:

- Each object must have `apiVersion`, `kind` and `metadata.name`.
- Each object must be a namespaced kind, for example `Deployment`, `Service` or `ConfigMap`.
  The full list is `SETUP_KINDS` in `backend/labs.py`.
- An object can have no namespace or the lab namespace. It cannot use a different namespace.

### Test the lab

1. Run `.venv/bin/pytest`. The tests load and validate all lab files, and each lab must have a machine solution.
2. Run `.venv/bin/pytest -m e2e`. The machine solution must pass all checks.
3. Start the app and open the quest.
4. Click "Start lab", do the task, and click "Check my work".

## Update the screenshots

The README images are in `docs/images/`. Take them from a running app at a window width of about 1100 px, at 2x scale.
Show real state: one quest done, and a lab with a mix of passed and failed checks.
