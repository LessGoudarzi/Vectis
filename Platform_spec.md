# Production Multi-Layer GIS Web Product Architecture & Docker Deployment Blueprint

This document outlines the complete architectural blueprint, codebase, and containerization strategy for launching a commercial multi-layer geospatial SaaS product. It uses a **Hybrid Architecture**: a high-performance **Python (FastAPI + DuckDB Spatial)** backend paired with a **React + Deck.gl + Mapbox + Tailwind CSS** glassmorphic frontend, fully dockerized for multi-cloud porting.

---

## 1. System Architecture & Containerization Strategy

### 1.1 Core Architecture
- **Frontend Container (`frontend`)**: React 18 (Vite, TypeScript, Tailwind CSS, Deck.gl v9, Mapbox GL v3). In production, static assets are built via multi-stage Node build and served through **Nginx** acting as a web server and API reverse proxy.
- **Backend Container (`backend`)**: Python 3.11 with **FastAPI** and **DuckDB In-Memory Spatial Engine**. Queries spatial files (GeoParquet / GeoJSON), performs spatial indexing/bounding-box filtering, and serves optimized GeoJSON streams to Deck.gl.
- **Data Volume Strategy**: Persistent storage mounted into DuckDB for fast vector querying or remote S3 loading via DuckDB's spatial extensions.

```text
       ┌────────────────────────────────────────────────────────┐
       │                   User Web Browser                     │
       └───────────────────────────┬────────────────────────────┘
                                   │ HTTP / Port 80
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │                  Nginx Reverse Proxy                   │
       │                   (Frontend Service)                   │
       └──────────────┬──────────────────────────┬──────────────┘
                      │                          │
        Static Assets │                          │ /api/ Proxy
                      ▼                          ▼
       ┌────────────────────────┐  ┌────────────────────────────┐
       │ React + Deck.gl Engine │  │   FastAPI Spatial API      │
       │ (Client WebGL Render)  │  │   (Python 3.11 Container)  │
       └────────────────────────┘  └─────────────┬──────────────┘
                                                 │
                                                 ▼
                                   ┌────────────────────────────┐
                                   │  DuckDB In-Memory Spatial  │
                                   │  (ST_Intersects / GeoJSON) │
                                   └────────────────────────────┘
```

---

## 2. Directory Layout

```text
gis-platform/
├── docker-compose.yml
├── docker-compose.prod.yml
├── .env.example
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── config.py
│   ├── database.py
│   ├── main.py
│   └── routers/
│       └── layers.py
└── frontend/
    ├── Dockerfile
    ├── nginx.conf
    ├── package.json
    ├── vite.config.ts
    ├── index.html
    ├── src/
    │   ├── App.tsx
    │   ├── main.tsx
    │   ├── index.css
    │   ├── types/
    │   │   └── gis.ts
    │   ├── hooks/
    │   │   ├── useLayerState.ts
    │   │   └── useGISData.ts
    │   ├── layers/
    │   │   └── layerFactory.ts
    │   └── components/
    │       ├── GISMapContainer.tsx
    │       └── LayerManager.tsx
    ├── postcss.config.js
    └── tailwind.config.js
```

---

## 3. Full Implementation Code Snippets

### 3.1 Backend Codebase (`/backend`)

#### `backend/requirements.txt`
```text
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
duckdb>=0.9.2
pydantic>=2.6.0
pydantic-settings>=2.1.0
```

#### `backend/config.py`
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "US GIS Spatial API Engine"
    DEBUG: bool = True
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173", "http://localhost"]
    MAPBOX_ACCESS_TOKEN: str = ""

    class Config:
        env_file = ".env"

settings = Settings()
```

#### `backend/database.py`
```python
import duckdb
import logging

logger = logging.getLogger("uvicorn")

class SpatialDatabase:
    def __init__(self):
        self.conn = duckdb.connect(database=':memory:')
        self._init_spatial()

    def _init_spatial(self):
        logger.info("Initializing DuckDB Spatial Extension...")
        self.conn.execute("INSTALL spatial; LOAD spatial;")
        self._seed_mock_layers()

    def _seed_mock_layers(self):
        # Layer 1: Automobile Assembly Plants
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS auto_plants AS 
            SELECT id, name, brand, capacity, ST_Point(lon, lat) as geom
            FROM (VALUES 
                (1, 'Detroit Assembly Complex', 'Stellantis', 350000, -82.9780, 42.3664),
                (2, 'Smyrna Assembly Plant', 'Nissan', 640000, -86.5186, 35.9828),
                (3, 'Gigafactory Texas', 'Tesla', 500000, -97.6171, 30.2223),
                (4, 'Chattanooga Plant', 'Volkswagen', 250000, -85.1328, 35.0806),
                (5, 'Greer Plant', 'BMW', 450000, -82.2263, 34.8958)
            ) AS t(id, name, brand, capacity, lon, lat);
        ''')

        # Layer 2: Power Grid Lines
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS power_grid AS
            SELECT id, voltage_kv, line_name, ST_GeomFromText(wkt) as geom
            FROM (VALUES
                (101, 500, 'Midwest High Voltage Interconnect', 'LINESTRING(-82.978 42.366, -86.518 35.982, -85.132 35.080)'),
                (102, 345, 'Southern Power Corridor', 'LINESTRING(-97.617 30.222, -85.132 35.080)'),
                (103, 765, 'Eastern Trunk Line', 'LINESTRING(-82.226 34.895, -82.978 42.366)')
            ) AS t(id, voltage_kv, line_name, wkt);
        ''')

    def get_layer_geojson(self, table_name: str, bbox: tuple = None) -> str:
        bbox_filter = ""
        if bbox:
            min_lon, min_lat, max_lon, max_lat = bbox
            bbox_filter = f"WHERE ST_Intersects(geom, ST_MakeEnvelope({min_lon}, {min_lat}, {max_lon}, {max_lat}))"

        query = f'''
            SELECT json_object(
                'type', 'FeatureCollection',
                'features', COALESCE(json_group_array(
                    json_object(
                        'type', 'Feature',
                        'geometry', json(ST_AsGeoJSON(geom)),
                        'properties', struct_pack(t.* EXCLUDE (geom))
                    )
                ), json_array())
            ) AS geojson
            FROM {table_name} t
            {bbox_filter};
        '''
        result = self.conn.execute(query).fetchone()
        return result[0] if result and result[0] else '{"type": "FeatureCollection", "features": []}'

db = SpatialDatabase()
```

#### `backend/routers/layers.py`
```python
from fastapi import APIRouter, Query, HTTPException, Response
from database import db
from typing import Optional

router = APIRouter(prefix="/api/v1/layers", tags=["Spatial Layers"])

VALID_LAYERS = ["auto_plants", "power_grid"]

@router.get("/{layer_id}")
async def get_layer_data(
    layer_id: str,
    min_lon: Optional[float] = Query(None),
    min_lat: Optional[float] = Query(None),
    max_lon: Optional[float] = Query(None),
    max_lat: Optional[float] = Query(None)
):
    table_name = layer_id.replace("-", "_")
    if table_name not in VALID_LAYERS:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")

    bbox = None
    if all(v is not None for v in [min_lon, min_lat, max_lon, max_lat]):
        bbox = (min_lon, min_lat, max_lon, max_lat)

    geojson_raw = db.get_layer_geojson(table_name, bbox)
    return Response(content=geojson_raw, media_type="application/json")
```

#### `backend/main.py`
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import settings
from routers import layers

app = FastAPI(
    title=settings.APP_NAME,
    openapi_url="/openapi.json" if settings.DEBUG else None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(layers.router)

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": settings.APP_NAME}
```

#### `backend/Dockerfile`
```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends     build-essential     curl     && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

### 3.2 Frontend Codebase (`/frontend`)

#### `frontend/package.json`
```json
{
  "name": "gis-platform-frontend",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "@deck.gl/aggregation-layers": "^9.0.0",
    "@deck.gl/core": "^9.0.0",
    "@deck.gl/geo-layers": "^9.0.0",
    "@deck.gl/layers": "^9.0.0",
    "@deck.gl/react": "^9.0.0",
    "lucide-react": "^0.344.0",
    "mapbox-gl": "^3.2.0",
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-map-gl": "^7.1.7"
  },
  "devDependencies": {
    "@types/node": "^20.11.0",
    "@types/react": "^18.2.0",
    "@types/react-dom": "^18.2.0",
    "@vitejs/plugin-react": "^4.2.1",
    "autoprefixer": "^10.4.18",
    "postcss": "^8.4.35",
    "tailwindcss": "^3.4.1",
    "typescript": "^5.3.3",
    "vite": "^5.1.4"
  }
}
```

#### `frontend/src/types/gis.ts`
```typescript
export type LayerId = 'auto-plants' | 'power-grid';

export interface LayerConfig {
  id: LayerId;
  name: string;
  visible: boolean;
  opacity: number;
  colorHex: string;
  zIndex: number;
}
```

#### `frontend/src/hooks/useLayerState.ts`
```typescript
import { useState, useCallback } from 'react';
import { LayerConfig, LayerId } from '../types/gis';

export const INITIAL_LAYERS: LayerConfig[] = [
  { id: 'auto-plants', name: 'Automobile Assembly Plants', visible: true, opacity: 0.9, colorHex: '#F59E0B', zIndex: 2 },
  { id: 'power-grid', name: 'High-Voltage Power Lines', visible: true, opacity: 0.8, colorHex: '#06B6D4', zIndex: 1 },
];

export function useLayerState() {
  const [layers, setLayers] = useState<LayerConfig[]>(INITIAL_LAYERS);

  const toggleVisibility = useCallback((id: LayerId) => {
    setLayers((prev) =>
      prev.map((lyr) => (lyr.id === id ? { ...lyr, visible: !lyr.visible } : lyr))
    );
  }, []);

  const updateOpacity = useCallback((id: LayerId, opacity: number) => {
    setLayers((prev) =>
      prev.map((lyr) => (lyr.id === id ? { ...lyr, opacity } : lyr))
    );
  }, []);

  return { layers, toggleVisibility, updateOpacity };
}
```

#### `frontend/src/hooks/useGISData.ts`
```typescript
import { useState, useEffect } from 'react';

const API_BASE = '/api/v1/layers';

export function useGISData() {
  const [datasets, setDatasets] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    async function loadLayers() {
      try {
        const [autoPlantsRes, powerGridRes] = await Promise.all([
          fetch(`${API_BASE}/auto-plants`),
          fetch(`${API_BASE}/power-grid`),
        ]);

        const autoPlants = await autoPlantsRes.json();
        const powerGrid = await powerGridRes.json();

        setDatasets({
          'auto-plants': autoPlants,
          'power-grid': powerGrid,
        });
      } catch (err) {
        console.error('Failed to load GIS datasets:', err);
      } finally {
        setLoading(false);
      }
    }

    loadLayers();
  }, []);

  return { datasets, loading };
}
```

#### `frontend/src/layers/layerFactory.ts`
```typescript
import { GeoJsonLayer } from '@deck.gl/layers';
import { LayerConfig } from '../types/gis';

const hexToRgb = (hex: string): [number, number, number] => {
  const num = parseInt(hex.replace('#', ''), 16);
  return [(num >> 16) & 255, (num >> 8) & 255, num & 255];
};

export function createDeckGLLayers(
  configs: LayerConfig[],
  datasets: Record<string, any>,
  onHover: (info: any) => void
) {
  const sorted = [...configs].sort((a, b) => a.zIndex - b.zIndex);

  return sorted
    .filter((config) => config.visible)
    .map((config) => {
      const rgb = hexToRgb(config.colorHex);
      const data = datasets[config.id];
      if (!data) return null;

      switch (config.id) {
        case 'auto-plants':
          return new GeoJsonLayer({
            id: config.id,
            data,
            pickable: true,
            opacity: config.opacity,
            pointRadiusScale: 10,
            pointRadiusMinPixels: 6,
            getFillColor: [...rgb, 220],
            getLineColor: [255, 255, 255, 255],
            getLineWidth: 2,
            lineWidthMinPixels: 2,
            onHover,
          });

        case 'power-grid':
          return new GeoJsonLayer({
            id: config.id,
            data,
            pickable: true,
            opacity: config.opacity,
            getLineColor: [...rgb, 220],
            getLineWidth: 3,
            lineWidthMinPixels: 3,
            onHover,
          });

        default:
          return null;
      }
    })
    .filter(Boolean);
}
```

#### `frontend/src/components/LayerManager.tsx`
```tsx
import React from 'react';
import { LayerConfig, LayerId } from '../types/gis';
import { Eye, EyeOff, Sliders } from 'lucide-react';

interface LayerManagerProps {
  layers: LayerConfig[];
  onToggle: (id: LayerId) => void;
  onOpacityChange: (id: LayerId, value: number) => void;
}

export const LayerManager: React.FC<LayerManagerProps> = ({
  layers,
  onToggle,
  onOpacityChange,
}) => {
  const activeCount = layers.filter((l) => l.visible).length;

  return (
    <div className="absolute top-4 left-4 z-20 w-80 rounded-xl border border-slate-700/50 bg-slate-900/80 p-4 shadow-2xl backdrop-blur-md text-slate-100">
      <div className="mb-4 flex items-center justify-between border-b border-slate-700/60 pb-3">
        <div className="flex items-center gap-2">
          <Sliders className="h-5 w-5 text-cyan-400" />
          <h2 className="font-semibold text-sm uppercase tracking-wider">Layer Control</h2>
        </div>
        <span className="rounded-full bg-cyan-500/20 px-2.5 py-0.5 text-xs font-bold text-cyan-400 border border-cyan-500/30">
          {activeCount} / {layers.length} Active
        </span>
      </div>

      <div className="space-y-3">
        {layers.map((lyr) => (
          <div
            key={lyr.id}
            className={`rounded-lg border p-3 transition-all ${
              lyr.visible
                ? 'border-slate-600 bg-slate-800/60'
                : 'border-slate-800 bg-slate-950/40 opacity-60'
            }`}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span
                  className="h-3 w-3 rounded-full border border-white/20"
                  style={{ backgroundColor: lyr.colorHex }}
                />
                <span className="text-xs font-medium text-slate-200">{lyr.name}</span>
              </div>

              <button
                onClick={() => onToggle(lyr.id)}
                className="rounded p-1 text-slate-400 hover:bg-slate-700 hover:text-white"
              >
                {lyr.visible ? <Eye className="h-4 w-4 text-cyan-400" /> : <EyeOff className="h-4 w-4" />}
              </button>
            </div>

            {lyr.visible && (
              <div className="mt-2.5 flex items-center gap-3 pt-2 border-t border-slate-700/40">
                <span className="text-[10px] text-slate-400">Opacity</span>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={lyr.opacity}
                  onChange={(e) => onOpacityChange(lyr.id, parseFloat(e.target.value))}
                  className="h-1 w-full cursor-pointer appearance-none rounded-lg bg-slate-700 accent-cyan-400"
                />
                <span className="text-[10px] text-slate-300 font-mono">
                  {Math.round(lyr.opacity * 100)}%
                </span>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};
```

#### `frontend/src/components/GISMapContainer.tsx`
```tsx
import React, { useState, useMemo } from 'react';
import DeckGL from '@deck.gl/react';
import { Map } from 'react-map-gl/mapbox';
import { useLayerState } from '../hooks/useLayerState';
import { useGISData } from '../hooks/useGISData';
import { createDeckGLLayers } from '../layers/layerFactory';
import { LayerManager } from './LayerManager';
import 'mapbox-gl/dist/mapbox-gl.css';

const INITIAL_VIEW_STATE = {
  longitude: -98.5795,
  latitude: 39.8283,
  zoom: 4,
  pitch: 35,
  bearing: 0,
};

const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN || '';

export const GISMapContainer: React.FC = () => {
  const { layers, toggleVisibility, updateOpacity } = useLayerState();
  const { datasets } = useGISData();
  const [hoverInfo, setHoverInfo] = useState<any>(null);

  const deckLayers = useMemo(
    () => createDeckGLLayers(layers, datasets, setHoverInfo),
    [layers, datasets]
  );

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-slate-950">
      <LayerManager
        layers={layers}
        onToggle={toggleVisibility}
        onOpacityChange={updateOpacity}
      />

      <DeckGL
        initialViewState={INITIAL_VIEW_STATE}
        controller={true}
        layers={deckLayers}
        getCursor={({ isHovering }) => (isHovering ? 'pointer' : 'default')}
      >
        <Map
          mapboxAccessToken={MAPBOX_TOKEN}
          mapStyle="mapbox://styles/mapbox/dark-v11"
          reuseMaps
        />
      </DeckGL>

      {hoverInfo?.object && (
        <div
          className="absolute z-30 pointer-events-none rounded-lg border border-slate-700 bg-slate-900/90 p-3 text-xs text-white shadow-xl backdrop-blur-md"
          style={{ left: hoverInfo.x + 12, top: hoverInfo.y + 12 }}
        >
          <div className="font-bold text-cyan-400 mb-1">
            {hoverInfo.layer?.id.toUpperCase()}
          </div>
          <pre className="font-mono text-[11px] text-slate-300">
            {JSON.stringify(hoverInfo.object.properties, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
};
```

#### `frontend/src/App.tsx`
```tsx
import React from 'react';
import { GISMapContainer } from './components/GISMapContainer';

export const App: React.FC = () => {
  return <GISMapContainer />;
};

export default App;
```

#### `frontend/nginx.conf`
```nginx
server {
    listen 80;
    server_name localhost;

    location / {
        root /usr/share/nginx/html;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://backend:8000/api/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }
}
```

#### `frontend/Dockerfile`
```dockerfile
# Stage 1: Build React static assets
FROM node:20-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci

COPY . .
ARG VITE_MAPBOX_TOKEN
ENV VITE_MAPBOX_TOKEN=$VITE_MAPBOX_TOKEN
RUN npm run build

# Stage 2: Serve via Nginx
FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

---

### 3.3 Docker Compose Orchestration (`docker-compose.yml`)

```yaml
version: '3.8'

services:
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      - DEBUG=True
      - ALLOWED_ORIGINS=["http://localhost:3000","http://localhost:5173","http://localhost"]
    volumes:
      - ./backend:/app
    restart: unless-stopped

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
      args:
        - VITE_MAPBOX_TOKEN=${MAPBOX_TOKEN}
    ports:
      - "80:80"
    depends_on:
      - backend
    restart: unless-stopped
```

---

## 4. GitHub Copilot Execution Matrix (Discrete Testable Prompts)

Copy and feed these exact prompts in sequence to **GitHub Copilot / Cursor** to build and verify the system step-by-step.

### Step 1: Project & Backend Initialization
> **Copilot Prompt:**
> "Create a Python 3.11 FastAPI backend directory structure under `/backend`. Create `requirements.txt` with `fastapi`, `uvicorn`, `duckdb`, `pydantic-settings`. Write `database.py` initializing an in-memory DuckDB connection, loading the spatial extension (`INSTALL spatial; LOAD spatial;`), and creating mock tables for `auto_plants` (Point geometry) and `power_grid` (LineString geometry). Verify by running `python -c 'import database'`."

### Step 2: Spatial GeoJSON Router
> **Copilot Prompt:**
> "In `/backend/routers/layers.py`, write a FastAPI APIRouter serving `GET /api/v1/layers/{layer_id}`. The router must convert `{layer_id}` into DuckDB SQL queries utilizing `ST_AsGeoJSON(geom)` to dynamically construct a GeoJSON FeatureCollection. Include optional `min_lon`, `min_lat`, `max_lon`, `max_lat` bounding-box parameters filtering using `ST_Intersects` and `ST_MakeEnvelope`. Add CORS in `main.py` and write a PyTest test verifying that `/api/v1/layers/auto-plants` returns HTTP 200 and a valid GeoJSON object."

### Step 3: Backend Dockerization Verification
> **Copilot Prompt:**
> "Create `/backend/Dockerfile` using `python:3.11-slim`. Install build-essential dependencies, copy `requirements.txt`, install dependencies, and set CMD to `uvicorn main:app --host 0.0.0.0 --port 8000`. Test by running `docker build -t gis-backend ./backend` and executing `docker run -p 8000:8000 gis-backend`, then checking `http://localhost:8000/health`."

### Step 4: React + Deck.gl Frontend Foundation
> **Copilot Prompt:**
> "Under `/frontend`, setup a Vite + React + TypeScript project with Tailwind CSS. Install `@deck.gl/core`, `@deck.gl/react`, `@deck.gl/layers`, `react-map-gl`, `mapbox-gl`, and `lucide-react`. Create `src/types/gis.ts` defining `LayerConfig` with fields for `id`, `name`, `visible`, `opacity`, `colorHex`, `zIndex`. Write `useLayerState` hook managing state for `auto-plants` and `power-grid` layers."

### Step 5: Data Fetching & Deck.gl Layer Factory
> **Copilot Prompt:**
> "Write `src/hooks/useGISData.ts` to fetch `/api/v1/layers/auto-plants` and `/api/v1/layers/power-grid`. Write `src/layers/layerFactory.ts` that takes layer configs and datasets, returning Deck.gl `GeoJsonLayer` instances mapped to hex colors and opacity sliders. Build `GISMapContainer.tsx` integrating DeckGL and Mapbox Dark Style with hover tooltips."

### Step 6: Glassmorphic UI Panel Integration
> **Copilot Prompt:**
> "Build `src/components/LayerManager.tsx` as a floating glassmorphic sidebar (`bg-slate-900/80 backdrop-blur-md`). Render active layer badges, visibility eye toggles, color swatches, and HTML range sliders bound to layer opacity state. Verify that toggling a layer or adjusting the slider updates Deck.gl canvas rendering instantly."

### Step 7: Docker Compose Production Deployment
> **Copilot Prompt:**
> "Create `/frontend/Dockerfile` with a 2-stage build: Stage 1 builds static Vite production bundles using Node 20; Stage 2 copies `/dist` into `nginx:alpine` and configures `nginx.conf` to route `/api/` traffic to `http://backend:8000/api/`. Create a root `docker-compose.yml` linking `frontend` and `backend`. Run `docker-compose up --build` and verify full end-to-end functionality at `http://localhost`."
