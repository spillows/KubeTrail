# Security Policy

## Supported versions

KubeTrail has no releases yet. We fix security problems on the `main` branch only.

| Version | Supported |
| --- | --- |
| `main` | Yes |

## Report a vulnerability

Do not open a public issue for a security problem.

1. Go to the [Security tab](https://github.com/spillows/KubeTrail/security) of this repository.
2. Click **Report a vulnerability**.
3. Fill in the form.

Give this information in your report:

- What the problem is.
- The steps that cause the problem.
- The result of the problem, for example data that the app reads or deletes.
- The commit of `main` that you used.
- Your OS, and the versions of minikube, kubectl, Helm and Terraform.

## What happens next

- We reply to your report in 7 days or less.
- We tell you if we accept the problem.
- We tell you when the fix is on `main`.
- We give you credit in the advisory if you want it.

## Scope

KubeTrail runs on the computer of the learner. It touches only a minikube context. These problems are in scope:

- The app runs a command on a cluster that is not minikube.
- The app changes or deletes a namespace that it did not make.
- The app changes or deletes an object outside a `lab-*` namespace.
- The app reads or writes the files of the learner.
- The app sends the `data` of a Secret to the browser.
- A lab file, a content file or an API request makes the app run a command that it must not run.

These problems are not in scope:

- A problem in minikube, kubectl, Helm, Terraform or Docker. Report it to that project.
- The result of a command that the learner types in a terminal.
- A password or a key in a lab file. These values are demo values for the labs, for example in `labs/k9.yaml`.
- A learner who marks a quest as done without the work. `progress.json` is a local file.
