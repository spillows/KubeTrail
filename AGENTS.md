# Rules for agents

- Follow `docs/designs/course-expansion.md`. It is the design and the catalog of record for each quest and lab.
- Follow `CONTRIBUTING.md` for the rules of quests, labs and checks.
- Write all text in ASD-STE100 (Simplified Technical English).
- Run `.venv/bin/pytest` before each commit. Run `.venv/bin/pytest -m e2e` against a real minikube before a lab merges.
- Never change a quest id.
- The app touches only a minikube context and only the `lab-*` namespaces that it stamped. Do not weaken the guard.
