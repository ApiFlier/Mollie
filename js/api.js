/**
 * API abstraction layer for Mollie's Guide.
 *
 * All backend calls route through this module. If we ever swap the
 * Flask API for a SQLite-backed Android build, only this file changes.
 *
 * Frontend code should never hit fetch() directly - always go through
 * MolliesAPI.
 */

const MolliesAPI = (() => {
  // When served by nginx, the API lives at /api/* (proxied to Flask).
  // For local dev pointing at Flask directly, set this to http://localhost:8091
  const BASE = "/api";

  async function request(path, params = null) {
    let url = BASE + path;
    if (params) {
      const qs = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) {
        if (v !== null && v !== undefined && v !== "") {
          qs.append(k, v);
        }
      }
      const qsStr = qs.toString();
      if (qsStr) url += "?" + qsStr;
    }

    try {
      const r = await fetch(url);
      if (!r.ok) {
        throw new Error(`HTTP ${r.status} on ${url}`);
      }
      return await r.json();
    } catch (err) {
      console.error("API error:", err);
      throw err;
    }
  }

  return {
    health: () => request("/health"),
    getCategories: () => request("/categories"),
    getDistinctCrops: () => request("/crops/distinct"),
    getLocations: (filters = {}) => request("/locations", filters),
    getLocation: (id) => request(`/locations/${id}`),

    getNotes: (locId) => request(`/locations/${locId}/notes`),
    addNote: async (locId, text) => {
      const r = await fetch(`/api/locations/${locId}/notes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note: text })
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return await r.json();
    },
    deleteNote: async (noteId) => {
      const r = await fetch(`/api/notes/${noteId}`, { method: "DELETE" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return await r.json();
    }
  };
})();
