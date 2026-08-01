# Vectis Yield: Unified Build Guide

## Why this doc exists

You have two source documents that describe two different layers of the same product, and they don't currently agree with each other:

- **`Platform_spec.md`** — the technical architecture. FastAPI + DuckDB spatial backend, React + Deck.gl + Mapbox frontend, Dockerized. This is treated as the **authoritative architecture** below — it's concrete, buildable, and already partially implemented in `power/`.
- **`Vectis Yield Paperclip Initialization Guide.md`** — the multi-agent research swarm (Paperclip) that produces the industrial/economic data Vectis Yield sells: a CEO orchestrator plus six domain agents plus a "web experience" agent.

They were written independently, so they conflict in two concrete ways (details in the next section). This guide resolves those conflicts and gives you one linear build order instead of two documents to reconcile in your head every time you touch either one.

---

## Conflicts found, and how they're resolved

### 1. Two different frontend stacks
The Paperclip guide's `agent-web-experience` (Step 10) says it renders into a **"React/Next.js dynamic dashboard."** `Platform_spec.md` specifies **Vite + React + Deck.gl + Mapbox**, not Next.js, and there's no SSR requirement anywhere in the project.

**Resolution:** `Platform_spec.md` wins. `agent-web-experience`'s job is redefined as *producing the JSON that the existing Vite/Deck.gl frontend consumes as a new layer*, not standing up a second, competing frontend. Don't build a Next.js app.

### 2. The agent payload has no geometry
`COMPANY.md`'s `IndustrialConvergencePayload` schema (also duplicated, with a syntax error — missing comma after the `$schema` key — in `test.json`) has `facility_id` and `corridor` but **no lat/lon**. `Platform_spec.md`'s DuckDB layer requires `ST_Point(lon, lat)` to render anything on the map. Without coordinates, the CEO orchestrator's output is structurally incompatible with the map backend.

**Resolution:** add a `location` object (`lat`, `lon`, optionally `address`) to the schema as a required field. Every domain agent that emits a `facility_id` must resolve it to coordinates before the CEO orchestrator accepts the payload — this is now Step 2 below instead of being silently assumed.

### 3. Two unrelated codebases already exist under this stack
`power/` is a **working, already-committed** Flask + SQLite + Leaflet app (per `power/outline.md`) that ingests real HIFLD transmission-line and EIA power-plant data — it's more mature in data-handling terms than anything in `Platform_spec.md`, which is still a from-scratch blueprint (FastAPI/DuckDB/React/Deck.gl, nothing built yet).

**Resolution:** treat `Platform_spec.md` as the **target architecture to migrate toward**, and `power/`'s ingestion scripts (`ingest_to_sqlite.py`) as the reference implementation for *how* to shape real-world geospatial data — the DuckDB loader in Step 4 below should follow the same filtering/bucketing patterns already proven in `power/ingest_to_sqlite.py`, not reinvent them. This is a migration, not a rewrite from zero.

### 4. Paperclip import path is unverified
`import_it_to_paperclip.md` lists three candidate commands (`paperclip import`, `companies.sh add`, `companies.sh update`) with a literal `#### no import command??` — i.e., this was never confirmed to work. Flagged as an open risk in Step 8; don't block the rest of the build on it.

---

## Rationalized Step-by-Step Plan

### Phase 0 — Business scaffolding (from Paperclip guide's TODO list)
1. Domain registration — **done** (`vectisyield.com`).
2. Marketing agent to build followers — **not started**. Defer to Phase 6 (it's a content-generation consumer of the platform, not a blocker for it).
3. Investor orientation materials (startup/early-stage opportunity framing) — **not started**. Defer to Phase 6, same reason.
4. Cloud environment — this is exactly what `Platform_spec.md` Section 3.3 (Docker Compose) plus Phase 5 below solves. Not a separate task.

### Phase 1 — Agent swarm scaffolding (Paperclip guide, Steps 1–10)
Run as-is; nothing here conflicts with the platform:
1. Create the `vectis-yield-spec/agents/*` directory tree.
2. Write `COMPANY.md` with the shared schema — **but apply the Phase-owned schema fix from Conflict #2 before agents start producing data** (add `location.lat` / `location.lon`).
3. Write each `AGENTS.md` (CEO orchestrator, auto capacity, defense hardware, robotics, energy grid, labor/skills, macro yield, web experience) exactly as specified.

Status: directory and all 8 `AGENTS.md` files already exist in `vectis-yield-spec/` — this phase is functionally complete except for the schema patch.

### Phase 2 — Patch the shared schema (new, closes Conflict #2)
1. Edit `COMPANY.md`'s JSON schema: add
   ```json
   "location": {
     "type": "object",
     "required": ["lat", "lon"],
     "properties": {
       "lat": { "type": "number", "minimum": -90, "maximum": 90 },
       "lon": { "type": "number", "minimum": -180, "maximum": 180 }
     }
   }
   ```
   to `required` and `properties` on `IndustrialConvergencePayload`.
2. Update `agent-auto-capacity` and `agent-defense-hardware`'s `AGENTS.md` responsibilities to include resolving facility addresses to coordinates (they're the two agents that originate new `facility_id`s).
3. Fix or delete `test.json` — it's currently invalid JSON (missing comma) and duplicates `COMPANY.md`'s schema; keeping two copies in sync is a maintenance trap. Recommend deleting it and pointing anything that referenced it at `COMPANY.md`.

### Phase 3 — Backend platform (Platform_spec.md §3.1, Steps 1–2)
1. Scaffold `/backend` (FastAPI, DuckDB spatial) per `Platform_spec.md`.
2. In `database.py`, add a **third** seed table — `industrial_convergence` — alongside the existing `auto_plants` / `power_grid` mocks, using `ST_Point(location.lon, location.lat)` from the patched schema. This is the ingestion point for the CEO orchestrator's output (file drop, or a small `/api/v1/ingest` POST endpoint that validates against the schema and upserts into DuckDB — pick whichever matches how Paperclip actually delivers payloads, see Phase 5).
3. Extend `routers/layers.py`'s `VALID_LAYERS` to include `industrial_convergence`.
4. When building the loader, mirror the state-filtering and voltage/capacity-bucketing patterns already working in `power/ingest_to_sqlite.py` rather than writing new heuristics from scratch (Conflict #3).

### Phase 4 — Frontend platform (Platform_spec.md §3.2, Steps 4–6)
1. Scaffold `/frontend` (Vite + React + TS + Tailwind + Deck.gl + Mapbox) per spec.
2. Add a fourth `LayerConfig` entry for `industrial-convergence` in `useLayerState.ts`, fetched in `useGISData.ts`, rendered via a new case in `layerFactory.ts` (likely a `GeoJsonLayer` similar to `auto-plants`, colored/sized by `macro_yield.estimated_annual_output_usd` or `energy_profile.energy_bottleneck_flag`).
3. This is where `agent-web-experience`'s actual job lands (Conflict #1) — it doesn't need its own app, it needs its output shaped to satisfy this layer's expected GeoJSON `properties`.

### Phase 5 — Wire the orchestrator to the platform (new, closes Conflict #1)
1. Decide the delivery mechanism from `agent-ceo` to the backend: either (a) the CEO orchestrator writes a validated JSON file that a watcher/cron re-runs the DuckDB seed step on, or (b) it POSTs to a new `/api/v1/ingest/industrial-convergence` FastAPI endpoint. (b) is simpler to reason about and matches the "dispatch the finalized payload" language already in the CEO's `AGENTS.md` — recommended default.
2. Update `agent-ceo`'s `AGENTS.md` "OUTPUT REQUIREMENTS" section to name the concrete endpoint instead of the vague "dispatch... to `agent-web-experience`."

### Phase 6 — Dockerize & deploy (Platform_spec.md §3.3 + Step 7, closes Phase 0 item 4)
1. Follow `Platform_spec.md`'s Docker Compose steps as written — `backend` + `frontend` services.
2. This *is* the "cloud environment" TODO from the Paperclip guide; deploy the compose stack to whatever host/cloud you pick (no architecture decision needed here beyond picking a provider).
3. Now that a live dashboard exists, build the **marketing agent** and **investor orientation** materials (Phase 0 items 2–3) as content that links to or embeds this deployed dashboard — they were blocked on having something real to point at.

### Phase 7 — Paperclip import (unresolved, flagged risk)
1. `import_it_to_paperclip.md` has three untested candidate commands and an explicit "no import command??" note. Before relying on this, verify which (if any) actually works against your Paperclip CLI version — don't assume `npx paperclip import` or `companies.sh add/update` are correct without a test run.
2. This phase is independent of Phases 1–6 — the agent specs and platform work regardless of how they get registered with Paperclip's own tooling.

---

## Summary of what changed vs. the two source docs

| Source doc | What it got right as-is | What this guide changed |
|---|---|---|
| `Platform_spec.md` | Full backend/frontend/Docker architecture — kept verbatim as Phases 3, 4, 6 | Added a third data layer (`industrial_convergence`) it didn't originally know about |
| Paperclip guide | Agent roles, responsibilities, budgets — kept verbatim as Phase 1 | Fixed schema (added geometry), redirected `agent-web-experience`'s target from "Next.js dashboard" to "existing Deck.gl layer," gave `agent-ceo` a concrete ingestion endpoint instead of a vague dispatch target |
