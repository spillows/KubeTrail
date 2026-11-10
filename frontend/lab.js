// The lab panel of a LAB or BOSS quest.
// build() in render.js adds an empty, hidden <div class="lab"> to each LAB
// quest. initLabs() fills the div only if the backend has a lab with the
// same id. The panel has Start, Check my work and Reset, the result of each
// check and the hints.
import { get, post } from "./api.js";
import { refreshCluster } from "./cluster.js";

const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
// Show `text` in a hint as inline code. The text is escaped first. Thus, a hint cannot add HTML.
const inline = s => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>");
const CONFIRM_MS = 5000;

// onPass(labId) runs when all checks of a lab pass.
export async function initLabs({ onPass }) {
  const r = await get("/labs");
  if (!r.ok) return;
  // If /needs fails, no panel disables Start lab. The backend still refuses an unmet need.
  const nr = r.data.some(l => l.needs.length) ? await get("/needs") : { ok: true, data: {} };
  const needs = nr.ok ? nr.data : {};
  r.data.forEach(lab => {
    const el = document.getElementById("lab-" + lab.id);
    if (!el) return;
    panel(el, lab, onPass, lab.needs.filter(t => needs[t] && !needs[t].met).map(t => needs[t].help));
    // Only "Check my work" can complete a lab quest. Thus, remove the manual button.
    const manual = document.getElementById("btn-" + lab.id);
    if (manual) manual.hidden = true;
  });
}

function panel(el, lab, onPass, unmet) {
  const ns = lab.namespace;
  el.innerHTML = `
    <div class="labhead"><span class="lbl">Lab on minikube</span><code>namespace ${esc(ns)}</code></div>
    ${unmet.length ? `<ul class="unmet">${unmet.map(h => `<li>${inline(h)}</li>`).join("")}</ul>` : ""}
    <div class="labnext" hidden>
      <span class="nextsay"></span>
      <div class="cmd"><pre></pre><button type="button" data-act="copy">Copy</button></div>
    </div>
    <ul class="checks">${lab.checks.map(c => `
      <li data-check="${esc(c.id)}" data-state="todo"><span class="cmark" aria-hidden="true">·</span><span class="say">${esc(c.say)}</span><span class="actual"></span><span class="why" hidden>${esc(c.why)}</span></li>`).join("")}
    </ul>
    <div class="labbtns">
      <button type="button" data-act="setup">Start lab</button>
      <button type="button" data-act="verify">Check my work</button>
      <button type="button" data-act="reset" class="danger">Reset</button>
    </div>
    <p class="labmsg" role="status" aria-live="polite"></p>
    ${lab.hints.length ? `<div class="hints"><ol></ol><button type="button" data-act="hint"></button></div>` : ""}`;
  el.hidden = false;

  const $ = s => el.querySelector(s);
  const buttons = [...el.querySelectorAll(".labbtns button")];
  const resetBtn = $('[data-act="reset"]');
  let shownHints = 0;
  let armTimer = null;

  const say = (text, level = "") => { const m = $(".labmsg"); m.textContent = text; m.dataset.level = level; };
  const startBtn = $('[data-act="setup"]');
  const busy = on => { buttons.forEach(b => { b.disabled = on; }); if (unmet.length) startBtn.disabled = true; };
  busy(false);
  const showNext = (text, cmd) => {
    $(".labnext .nextsay").textContent = text;
    $(".labnext pre").textContent = cmd;
    $(".labnext").hidden = false;
  };
  const useLabNs = `kubectl config set-context --current --namespace ${ns}`;

  const disarm = () => {
    clearTimeout(armTimer); armTimer = null;
    delete resetBtn.dataset.armed; resetBtn.textContent = "Reset";
  };

  const clearChecks = () => el.querySelectorAll(".checks li").forEach(li => {
    li.dataset.state = "todo";
    li.querySelector(".cmark").textContent = "·";
    li.querySelector(".actual").textContent = "";
    li.querySelector(".why").hidden = true;
  });

  const showHint = () => {
    const btn = $('[data-act="hint"]');
    if (!btn) return;
    $(".hints ol").innerHTML = lab.hints.slice(0, shownHints).map(h => `<li>${inline(h)}</li>`).join("");
    btn.hidden = shownHints >= lab.hints.length;
    btn.textContent = `Show hint ${shownHints + 1} of ${lab.hints.length}`;
  };
  showHint();

  // A 409 or 502 error can come from a change in the cluster. Thus, examine the cluster again.
  const failed = res => {
    say(res.error, "bad");
    if (res.status === 409 || res.status === 502 || res.status === 0) refreshCluster();
  };

  const actions = {
    async setup() {
      busy(true); say(`Setting up namespace ${ns}…`);
      const res = await post(`/labs/${lab.id}/setup`);
      busy(false);
      if (!res.ok) return failed(res);
      clearChecks();
      if (res.data.kubectlNamespace === ns) {
        $(".labnext").hidden = true;
        say(`The lab is ready in namespace ${ns}, and your kubectl commands go there. Do the task, then click "Check my work".`, "ok");
      } else {
        showNext(`Step 1: run this command first. Then your kubectl commands go to namespace ${ns}, not ${res.data.kubectlNamespace}.`, res.data.next);
        say(`The lab is ready in namespace ${ns}. Run the command above, do the task, then click "Check my work".`, "ok");
      }
    },

    async verify() {
      busy(true); say("Checking the cluster…");
      const res = await post(`/labs/${lab.id}/verify`);
      busy(false);
      if (!res.ok) return failed(res);
      res.data.checks.forEach(c => {
        const li = el.querySelector(`[data-check="${CSS.escape(c.id)}"]`);
        if (!li) return;
        li.dataset.state = c.passed ? "pass" : "fail";
        li.querySelector(".cmark").textContent = c.passed ? "✓" : "✗";
        const act = li.querySelector(".actual");
        act.classList.toggle("err", !!c.error);
        act.textContent = c.passed ? "" : c.error ? c.error : (c.actual === null ? "not found" : `found: ${c.actual}`);
        li.querySelector(".why").hidden = c.passed;
      });
      const n = res.data.checks.filter(c => c.passed).length;
      $(".labnext").hidden = true;
      if (res.data.passed) {
        say("All checks pass. The quest is complete.", "ok");
        onPass(lab.id);
      } else {
        const found = res.data.elsewhere.map(e => `Found ${e.get} in namespace ${e.namespaces.join(", ")}, not in ${ns}.`);
        const wrongNs = res.data.kubectlNamespace !== ns;
        if (wrongNs) found.unshift(`Your kubectl commands go to namespace ${res.data.kubectlNamespace}.`);
        say([`${n} of ${res.data.checks.length} checks pass.`, ...found].join(" "), "warn");
        if (wrongNs) showNext(`Run this command, then do the task again in namespace ${ns}:`, useLabNs);
      }
    },

    async reset() {
      // The first click arms the button. The second click deletes the namespace.
      if (!resetBtn.dataset.armed) {
        resetBtn.dataset.armed = "1";
        resetBtn.textContent = `Delete ${ns}? Click again`;
        armTimer = setTimeout(disarm, CONFIRM_MS);
        return;
      }
      disarm();
      busy(true); say(`Deleting namespace ${ns}. This can take up to 2 minutes.`);
      const res = await post(`/labs/${lab.id}/reset`);
      busy(false);
      if (!res.ok) return failed(res);
      clearChecks();
      $(".labnext").hidden = true;
      if (res.data.next) showNext("Your kubectl commands still go to the lab namespace. Run this command to go back to namespace default:", res.data.next);
      const after = lab.needs.includes("terraform") ? " Click Start lab before you run `terraform apply` again." : "";
      say((res.data.deleted ? `Namespace ${ns} is deleted.` : `Namespace ${ns} does not exist. There is nothing to delete.`) + after, "ok");
    },

    async copy() {
      const text = $(".labnext pre").textContent;
      const btn = $('[data-act="copy"]');
      try { await navigator.clipboard.writeText(text); btn.textContent = "Copied"; }
      catch (e) { btn.textContent = "Select and copy"; }
      setTimeout(() => { btn.textContent = "Copy"; }, 1500);
    },

    hint() { shownHints = Math.min(shownHints + 1, lab.hints.length); showHint(); },
  };

  el.addEventListener("click", e => {
    const b = e.target.closest("button[data-act]");
    if (!b || b.disabled) return;
    if (b.dataset.act !== "reset") disarm();
    actions[b.dataset.act]();
  });
}
