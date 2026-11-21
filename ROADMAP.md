# Roadmap

These items come after the course design in
[`docs/designs/course-expansion.md`](docs/designs/course-expansion.md). They are
not part of that design. Each item needs a reason before it moves into a
design.

1. **A `quiz` kind for READ quests.** A READ quest gets a few questions with
   more than one answer. The quest is done when the answers are correct. This
   replaces "Mark done". It is a new check kind, and it runs in the browser,
   not on the cluster. Add it if learners skip the READ quests.
2. **The `countAtLeast` and `contains` operators.** Add each one with the
   first lab that needs it.
3. **A weekly CI job that finds drift.** It runs the end-to-end test against
   new `helm`, `terraform` and minikube releases. The tests use fakes today,
   so CI does not see a change in those tools.
4. **The AI agent.** Two tasks only: `grade_rubric` and
   `author_lab`. Both give JSON against a fixed schema, and the app refuses a
   reply that does not agree with the schema. No shell, file or network tool.
   The program writes the files, not the model. The system prompt is a
   constant in `backend/agent.py`. Off by default: the learner adds an
   Anthropic API key. A new lab goes to a folder that the loader reads, goes
   through the same validator as a built-in lab, and must pass the end-to-end
   test. The UI shows it as unofficial.
5. **The Docker start** (`docker compose up`, with no Python on the host). The
   design and its test results are below. The course design changes it in
   three places. See "Changes from the course design".
6. **Linux.** The minikube `docker` driver on Linux gives the API server the
   address of the node container (for example `192.168.49.2:8443`), not a port
   on `127.0.0.1`. The Docker design below needs a change for Linux.
7. **Published images.** A GitHub Actions job builds the image with buildx on
   each tag. It sends `linux/amd64` and `linux/arm64` images to `ghcr.io`,
   with checksums.
8. **A "Further study" act** after Act XII, with READ links: Kubernetes the
   Hard Way, the Killercoda CKA scenarios, and the book
   *Terraform: Up & Running*.
9. **Debug logging.** No module logs today, so a failed check leaves no
   record. Add one DEBUG line in `cluster.run`, behind an environment
   variable: the arguments and the exit code. Never log stdout, which can hold
   Secret data.

## The Docker start

### Changes from the course design

The design below came before the course design. Three things are now
different:

* **The `needs` gate refuses every Helm and Terraform lab in a container.**
  The backend checks `helm` and `terraform` on its own `PATH`. The image does
  not hold them, by design. The Docker start must solve the tool check before
  it ships. For example, the learner states the tools on the host, or the
  check moves to the host.
* **The port forwarder must serve each minikube profile.** The advanced acts
  use a second profile, `kt-multi`, with its own published ports.
* **The image needs no `helm` and no `terraform`.** The app never runs them.
  The learner runs them on the host.

### Run it

```
git clone <repo>
cd kubetrail
docker compose up
```

Then open `http://localhost:8000`.

The app needs two things on the host: Docker, and a minikube profile that
runs. The host does not need Python. The learner also needs `kubectl` on the
host, because the learner types `kubectl` commands in each lab. The copy of
`kubectl` in the image is for the app only.

`docker compose up` builds the image from the `Dockerfile` in the repository.
Thus the app starts when there is no published image.

### What the image holds

- Python, the backend, and the frontend.
- The `kubectl` and `minikube` command-line tools. The backend calls both.
- The `docker` command-line tool. The `minikube` command calls it with the
  docker driver.
- `socat`, for the port forwarder. The next part tells the reason.
- No cluster. The minikube cluster of the learner stays on the host.

### How the container finds the cluster

The target platform is macOS with Docker Desktop. The same mechanism works on
Linux. Thus there is one code path, not two.

The compose file attaches these host directories:

- `$HOME/.kube`, read-only.
- `$HOME/.minikube`, read-only.
- The Docker socket. The `minikube` and `docker` commands need it.

The minikube kubeconfig holds absolute paths to the certificates in
`$HOME/.minikube`. The same is true for the client certificates. Thus the
compose file attaches each directory at the same absolute path in the
container. A different path makes the certificates fail.

**The problem.** With the docker driver, minikube publishes each port of the
node on the host at `127.0.0.1`. The port numbers are different on each
machine. In the container, `127.0.0.1` is the container. Thus `kubectl` and
`minikube` find nothing.

**The correction: a port forwarder.** At start, the entry point script reads
the published ports with `docker port <profile>`, for each profile. For each
port, it starts a `socat` listener on `127.0.0.1` in the container with the
same port number. Each listener sends the data to `host.docker.internal` on
that port.

The addresses in the kubeconfig are then correct in the container. Thus:

- The script does not change the kubeconfig. It makes no copy.
- The certificate stays correct, because the client connects to `127.0.0.1`.
  That address is in the certificate.
- The `minikube` command works. It needs SSH to the node on a second port,
  and the forwarder gives that port too.
- `backend/cluster.py` needs no change.

On macOS, Docker Desktop gives the name `host.docker.internal`. On Linux, this
line in the compose file gives the same name:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

**Test results.** These commands ran in a container against a real minikube
profile, with the mounts above and the forwarder:

| Command | Result |
|---|---|
| `kubectl get nodes` | The node, and the status `Ready`. |
| `minikube status -o json` | `Host: Running`, `APIServer: Running`. The same as the host. |
| `minikube profile list -o json` | The profile, with `Status: OK`. |
| `minikube addons list -o json` | The full list. |
| `kubectl create namespace` | The namespace. Write calls work. |

Read-only mounts gave no error. The `minikube` command did not try to write in
`$HOME/.minikube`.

**Without the forwarder, these are the failures.** Keep them in the tests:

- A change of the server URL to `host.docker.internal` gives this error:
  `x509: certificate is valid for ... localhost, not host.docker.internal`.
  The name is not in the certificate. A `tls-server-name: localhost` field
  corrects it. This is the second choice, for a host with no Docker socket.
  It corrects `kubectl` only. The `minikube` command still fails.
- `minikube status` gives `null` and exit code 7, because the SSH port is not
  available.

**A limit.** minikube gives new ports when it starts again. The learner must
then start the container again. The UI must give that message.

### Tests that come with the Docker start

- One test in the container: start the container against the minikube cluster
  of the host, then get `/api/cluster`. The reply must show `safe: true` and
  `running: true`. This test proves the port forwarder.
- A Docker smoke test in CI: build the image, start the container, and get
  `/api/cluster`. The reply must be 200 and must list the problems. This test
  does not need a cluster.

### The native path

`./run.sh` makes a virtual environment, installs the dependencies, starts
uvicorn, and opens the browser. It is the only path today. When the Docker
start ships, `./run.sh` stays for a learner who has Python and does not want
Docker.
