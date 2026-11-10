// The cluster line in the left panel, and the setup card above the quests.
// The line shows the minikube profile, the Kubernetes version and the node
// count. If there are problems, the line shows the first one, and the setup
// card shows all of them with the commands that correct them.
import { get } from "./api.js";

const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
// Show `text` in a problem as inline code. The text is escaped first.
const inline = s => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>");

export async function refreshCluster() {
  const el = document.getElementById("clusterState");
  const r = await get("/cluster");
  if (!r.ok) { card([r.error]); return show(el, "bad", r.error); }

  const s = r.data;
  card(s.problems || []);
  if (s.problems && s.problems.length) return show(el, s.safe ? "warn" : "bad", s.problems[0].replace(/`/g, ""));
  const n = (s.nodes || []).length;
  const parts = [s.profile, s.kubernetesVersion, `${n} node${n === 1 ? "" : "s"}`].filter(Boolean);
  show(el, "ok", parts.join(" · "));
}

function show(el, level, text) {
  el.dataset.level = level;
  el.querySelector(".ctext").textContent = text;
}

function card(problems) {
  const el = document.getElementById("setup");
  if (!problems.length) { el.hidden = true; el.innerHTML = ""; return; }
  el.innerHTML = `
    <div class="setuphead"><b>The labs need a running minikube</b><button type="button">Check again</button></div>
    <ul>${problems.map(p => `<li>${inline(p)}</li>`).join("")}</ul>
    <p>Most of the time, this fixes it: open Docker Desktop, then run this command in a terminal.</p>
    <pre>minikube start --driver=docker</pre>
    <p class="fine">The READ quests work without a cluster.</p>`;
  el.hidden = false;
  const btn = el.querySelector("button");
  btn.addEventListener("click", () => { btn.disabled = true; btn.textContent = "Checking…"; refreshCluster(); });
}
