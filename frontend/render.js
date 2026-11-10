const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const fmtMin = m => m >= 60 ? (Math.round(m / 6) / 10) + " h" : m + " min";
const pct = (d, n) => n ? Math.round(d / n * 100) : 0;

// A done quest folds to its title row. The ids in `open` stay open: the user
// clicked "Show", or completed the quest on this page.
const open = new Set();
export const keepOpen = id => open.add(id);

// Build the DOM for all acts and quests one time: one page for each act, and
// one link for each act in the left panel. Only one act page shows at a time.
// This function leaves the state values empty: marks, button labels and counts.
// render() adds these values.
// onToggle(questId) runs when the user clicks a "Mark done" button.
export function build(acts, onToggle) {
  const root = $("#acts"); root.innerHTML = "";
  $("#actNav").innerHTML = acts.map(a => `<li><a href="#act-${esc(a.id)}" data-nav="${esc(a.id)}"><span class="ncheck" aria-hidden="true">✓</span><span class="nnum">${esc(a.id)}</span><span class="ntitle">${esc(a.title)}</span><span class="ncount" data-navcount="${esc(a.id)}"></span><span class="nbar" aria-hidden="true"><span class="nfill"></span></span></a></li>`).join("");
  acts.forEach((a, i) => {
    const prev = acts[i - 1], nxt = acts[i + 1];
    const s = document.createElement("section"); s.className = "act"; s.id = "act-" + a.id; s.hidden = true;
    s.innerHTML = `<p class="crumb"><a href="#">Course</a> / Act ${esc(a.id)}</p>
      <div class="acthead"><h2>${esc(a.title)}</h2><span class="num">ACT ${esc(a.id)} · ${esc(a.duration)}</span></div>
      <p class="actdesc">${esc(a.description)}</p>
      <div class="actprog"><div class="meta"><b class="prog" data-prog="${esc(a.id)}"></b><span class="pct"></span></div><div class="track" role="progressbar" aria-valuemin="0" aria-valuemax="${a.quests.length}" aria-valuenow="0"><div class="fill"></div></div></div>
      <ol class="quests"></ol>
      <nav class="pager" aria-label="Acts">${prev ? `<a class="prev" href="#act-${esc(prev.id)}">← ${esc(prev.title)}</a>` : "<span></span>"}${nxt ? `<a class="nxt" href="#act-${esc(nxt.id)}">${esc(nxt.title)} →</a>` : ""}</nav>`;
    const ol = s.querySelector("ol");
    a.quests.forEach(q => {
      const li = document.createElement("li"); li.className = "q"; li.id = "q-" + q.id;
      li.innerHTML = `<span class="mark" aria-hidden="true">·</span><div class="qbody">
        <div class="qtop"><span class="type ${q.type === "BOSS" ? "boss" : ""}">${q.type}</span><span class="qtitle">${esc(q.title)}</span><span class="donechip">Done</span><span class="mins">${fmtMin(q.minutes)}</span><button type="button" class="fold" data-fold="${q.id}"></button></div>
        <p class="task">${esc(q.task)}</p>
        ${q.code ? `<pre>${esc(q.code)}</pre>` : ""}
        ${q.links && q.links.length ? `<ul class="links">${q.links.map(l => `<li><a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.title)} ↗</a></li>`).join("")}</ul>` : ""}
        ${q.answer ? `<details id="ans-${q.id}"><summary>Check yourself (answer first)</summary><div class="ans">${esc(q.answer)}</div></details>` : ""}
        ${q.type === "LAB" || q.type === "BOSS" ? `<div class="lab" id="lab-${q.id}" hidden></div>` : ""}
        <div class="qfoot"><button class="toggle" id="btn-${q.id}" data-q="${q.id}">Mark done</button><span class="donebadge">Done ✓</span><span class="when" id="when-${q.id}"></span></div>
      </div>`;
      ol.appendChild(li);
    });
    root.appendChild(s);
  });
  root.addEventListener("click", e => {
    const b = e.target.closest(".toggle");
    if (b) { keepOpen(b.dataset.q); onToggle(b.dataset.q); }
    const f = e.target.closest(".fold");
    if (f) {
      const id = f.dataset.fold; open.has(id) ? open.delete(id) : open.add(id);
      fold($("#q-" + id), id, true);
    }
  });
}

// Show the page of one act, or the course page if actId is null.
export function showPage(actId) {
  $("#home").hidden = actId !== null;
  document.querySelectorAll("section.act").forEach(s => { s.hidden = s.id !== "act-" + actId; });
  document.querySelectorAll("[data-nav]").forEach(l => {
    if (l.dataset.nav === actId) l.setAttribute("aria-current", "page"); else l.removeAttribute("aria-current");
  });
}

function fold(li, id, isDone) {
  const folded = isDone && !open.has(id);
  li.classList.toggle("folded", folded);
  const f = li.querySelector(".fold");
  f.textContent = folded ? "Show" : "Hide";
  f.setAttribute("aria-expanded", !folded);
}

// Update all values that come from the state: the quest marks and buttons,
// the act counters and bars in the left panel and on each act page,
// the total and the "next up" quest.
export function render(acts, done) {
  let doneCount = 0, total = 0, next = null;
  acts.forEach(a => {
    let d = 0;
    a.quests.forEach(q => {
      const isDone = !!done[q.id]; if (isDone) d++;
      if (!isDone && !next) next = { a, q };
      const li = $("#q-" + q.id); li.classList.toggle("done", isDone);
      fold(li, q.id, isDone);
      li.querySelector(".mark").textContent = isDone ? "+" : (next && next.q === q ? "~" : "·");
      $("#btn-" + q.id).textContent = isDone ? "Done ✓" : "Mark done";
      $("#btn-" + q.id).setAttribute("aria-pressed", isDone);
      $("#when-" + q.id).textContent = isDone && typeof done[q.id] === "string" ? "done " + done[q.id].slice(0, 10) : "";
    });
    const n = a.quests.length, p = pct(d, n), complete = d === n;
    const sec = document.getElementById("act-" + a.id);
    sec.classList.toggle("actdone", complete);
    sec.querySelector(".prog").textContent = `${d} of ${n} quests done`;
    sec.querySelector(".pct").textContent = p + "%";
    sec.querySelector(".actprog .track").setAttribute("aria-valuenow", d);
    sec.querySelector(".actprog .fill").style.width = p + "%";
    const link = document.querySelector(`[data-nav="${CSS.escape(a.id)}"]`);
    link.classList.toggle("complete", complete);
    link.querySelector(".nfill").style.width = p + "%";
    link.querySelector(".ncount").textContent = `${d}/${n}`;
    link.setAttribute("aria-label", `Act ${a.id}, ${a.title}, ${d} of ${n} quests done`);
    doneCount += d; total += n;
  });
  $("#doneText").textContent = `${doneCount} of ${total} quests done`;
  $("#donePct").textContent = pct(doneCount, total) + "%";
  const bar = $("#doneBar");
  bar.setAttribute("aria-valuemax", total); bar.setAttribute("aria-valuenow", doneCount);
  $("#doneFill").style.width = pct(doneCount, total) + "%";
  $("#nextQuest").innerHTML = next
    ? `<a href="#q-${next.q.id}">${esc(next.q.title)}</a> <span class="time">Act ${esc(next.a.id)} · ${next.q.type} · ${fmtMin(next.q.minutes)}</span>`
    : "All quests are done. ROADMAP.md lists what comes next.";
}
