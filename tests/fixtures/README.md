# Recorded data

Each file is the output of `kubectl get ... -o json` from a real run. Tests use
these files to check that the label selectors and names of the labs match what
the tools make. The `data` of each Secret is omitted: labs read only the names
and labels.

| File | Tool | Recorded with |
| --- | --- | --- |
| `helm/release-deployed.json` | `helm install`, `helm upgrade`, `helm rollback 1` | Helm v4.0.0, Kubernetes v1.37.0 |
| `helm/release-history.json` | The same release. Revisions 1 and 2 are `superseded`, revision 3 is `deployed`. | Helm v4.0.0, Kubernetes v1.37.0 |
| `helm/release-failed.json` | `helm install --wait` with an image tag that does not exist | Helm v4.0.0, Kubernetes v1.37.0 |
| `terraform/tfstate-secret.json` | `terraform apply` with the `kubernetes` backend, `secret_suffix = "t2"` | Terraform v1.13.4, provider hashicorp/kubernetes 2.38, Kubernetes v1.37.0 |
| `calico/pods.json` | `minikube start --driver=docker --cni=calico` | minikube v1.39.0, Kubernetes v1.37.0 |

When a tool changes its format, record the file again and update this table.
