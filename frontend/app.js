import { get } from "./api.js";
import { build, keepOpen, render, showPage } from "./render.js";
import * as progress from "./progress.js";
import { refreshCluster } from "./cluster.js";
import { initLabs } from "./lab.js";

const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const setStatus = text => { document.getElementById("saveState").textContent = text; };
let acts = [];
const draw = () => render(acts, progress.state.done);

// The URL hash selects the page. "#act-II" shows Act II. The id of an element
// in an act (for example "#q-k8") shows that act and scrolls to the element.
// No hash shows the course page.
function route() {
  const id = decodeURIComponent(location.hash.slice(1));
  const el = id ? document.getElementById(id) : null;
  const sec = el?.closest("section.act");
  showPage(sec ? sec.id.slice("act-".length) : null);
  if (sec && el !== sec) el.scrollIntoView();
  else window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);

// The backend gives the acts and the quests. Without them, the page has no
// quests. Thus, show the error in the status line and in the acts area.
async function start() {
  refreshCluster();
  const r = await get("/content");
  if (!r.ok) {
    setStatus("cannot load the quests");
    document.getElementById("acts").innerHTML =
      `<p class="loaderr" role="alert">Cannot load the quests: ${esc(r.error)}</p>`;
    document.getElementById("nextQuest").textContent = "no quests";
    return;
  }
  acts = r.data.acts;
  progress.configure({ status: setStatus, change: draw });
  build(acts, progress.toggle);
  draw();
  route();
  const loads = [progress.load()];
  // The backend records a lab quest when its checks pass. Then read the progress again.
  loads.push(initLabs({ onPass: id => { keepOpen(id); return progress.load(); } }));
  // The lab panels move the quests down when they load.
  // Thus, scroll to the quest in the URL again when the loads stop.
  Promise.allSettled(loads).then(() => { if (location.hash.startsWith("#q-")) route(); });
}

start();
