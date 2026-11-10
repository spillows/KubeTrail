// This module holds the progress state. The backend keeps the progress in
// progress.json.
// The module does not use the DOM. Callers give a status function and a
// repaint function to configure().
import { get, put, del } from "./api.js";

const SAVED = "saved in progress.json";

export const state = { done: {} };

let onStatus = () => {};        // Writes the text of the status line.
let onChange = () => {};        // Repaints the page after the state changes.

export function configure({ status, change }) {
  if (status) onStatus = status;
  if (change) onChange = change;
}

// Use the progress from a backend response, or show the error.
function apply(r, failText) {
  if (r.ok) { state.done = r.data.done; onStatus(SAVED); }
  else onStatus(`${failText}: ${r.error}`);
  onChange();
  return r.ok;
}

// Read the progress from the backend.
export async function load() {
  return apply(await get("/progress"), "cannot load progress");
}

// Mark a quest as done, or remove the mark. The backend refuses a lab quest.
// A lab quest is done only when its checks pass.
export async function toggle(id) {
  const path = "/progress/" + encodeURIComponent(id);
  return apply(state.done[id] ? await del(path) : await put(path), "not saved");
}
