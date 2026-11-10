// A small wrapper for the backend API.
// Each call returns { ok, status, data, error }. A call does not throw.
// If the backend does not respond, status is 0.

const NO_BACKEND = "The backend does not respond. Start it with: .venv/bin/uvicorn backend.main:app";

async function call(method, path) {
  let r;
  try {
    r = await fetch("/api" + path, { method, headers: { Accept: "application/json" } });
  } catch (e) {
    return { ok: false, status: 0, data: null, error: NO_BACKEND };
  }
  let data = null;
  try { data = await r.json(); } catch (e) { /* The body is not JSON. */ }
  if (!r.ok) {
    const detail = data && typeof data.detail === "string" ? data.detail : `The backend gave the error ${r.status}.`;
    return { ok: false, status: r.status, data, error: detail };
  }
  return { ok: true, status: r.status, data, error: null };
}

export const get = path => call("GET", path);
export const post = path => call("POST", path);
export const put = path => call("PUT", path);
export const del = path => call("DELETE", path);
