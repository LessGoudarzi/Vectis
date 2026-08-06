import React, { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import DeckGL from '@deck.gl/react';
import { WebMercatorViewport, FlyToInterpolator } from '@deck.gl/core';
import { Map } from 'react-map-gl';
import { useLayerState } from '../hooks/useLayerState';
import { useGISData } from '../hooks/useGISData';
import { useNetworkTrace } from '../hooks/useNetworkTrace';
import { createDeckGLLayers } from '../layers/layerFactory';
import { createOwnerHighlight } from '../owners';
import {
  NERC_REGION_SEARCH,
  STATE_SEARCH,
  PROCESS_SEARCH,
  DEFENSE_WORK_SEARCH,
  createAttributeHighlight,
} from '../attributeSearch';
import { createTraceHighlight, TraceableLayerId } from '../networkTrace';
import { ActiveHighlight } from '../types/gis';
import { LayerManager } from './LayerManager';
import { FeatureTooltip } from './FeatureTooltip';
import { InvestigatePanel, InvestigateMode } from './InvestigatePanel';
import { TracePanel } from './TracePanel';
import { AdminControls } from './AdminControls';
import 'mapbox-gl/dist/mapbox-gl.css';

const INITIAL_VIEW_STATE = {
  longitude: -98.5795,
  latitude: 39.8283,
  zoom: 4,
  pitch: 35,
  bearing: 0,
};

const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN || '';

// Recurses through a GeoJSON geometry's (possibly nested) coordinate
// arrays — same shape works for Point, LineString, and Polygon/MultiPolygon
// alike — expanding `bounds` ([minLng, minLat, maxLng, maxLat]) in place.
function expandBoundsWithGeometry(geometry: any, bounds: [number, number, number, number]): void {
  if (!geometry) return;
  if (geometry.type === 'GeometryCollection') {
    geometry.geometries?.forEach((g: any) => expandBoundsWithGeometry(g, bounds));
    return;
  }
  const walk = (coords: any): void => {
    if (typeof coords[0] === 'number') {
      const [lng, lat] = coords;
      if (lng < bounds[0]) bounds[0] = lng;
      if (lat < bounds[1]) bounds[1] = lat;
      if (lng > bounds[2]) bounds[2] = lng;
      if (lat > bounds[3]) bounds[3] = lat;
    } else {
      coords.forEach(walk);
    }
  };
  walk(geometry.coordinates);
}

// [minLng, minLat, maxLng, maxLat] across every currently-loaded feature
// that matches the active highlight, or null if nothing matches yet (empty
// query, no hits, or the relevant layer isn't loaded/visible) — used to fly
// the camera to the investigate result instead of leaving the user to hunt
// for it on the map.
function computeMatchedBounds(datasets: Record<string, any>, highlight: ActiveHighlight): [number, number, number, number] | null {
  const bounds: [number, number, number, number] = [Infinity, Infinity, -Infinity, -Infinity];
  let found = false;
  for (const layerId of Object.keys(datasets)) {
    const features = datasets[layerId]?.features ?? [];
    for (const feature of features) {
      if (highlight.isMatch(layerId as any, feature.properties)) {
        found = true;
        expandBoundsWithGeometry(feature.geometry, bounds);
      }
    }
  }
  return found ? bounds : null;
}

// Matches the app chrome's own background (Tailwind slate-950) instead of
// dark-v11's stock gray, so the map reads as part of the UI rather than a
// separate layer dropped on top. Water gets a distinct, slightly lighter
// shade (slate-900) — an earlier version flattened land and water to the
// identical color, which erased every coastline. Checked dark-v11's actual
// style JSON (via the Styles API) rather than guessing at layer ids: the
// background/fill layers are land (background), national-park, landuse,
// water, land-structure-polygon, aeroway-polygon, building.
const LAND_COLOR = '#020617'; // slate-950
const WATER_COLOR = '#0f172a'; // slate-900 — one step lighter, keeps coastlines visible

function recolorBasemap(evt: any) {
  const map = evt.target;
  if (!map.isStyleLoaded()) return;
  const layers = map.getStyle()?.layers ?? [];
  for (const layer of layers) {
    try {
      if (layer.type === 'background') {
        map.setPaintProperty(layer.id, 'background-color', LAND_COLOR);
      } else if (layer.type === 'fill') {
        map.setPaintProperty(layer.id, 'fill-color', layer.id === 'water' ? WATER_COLOR : LAND_COLOR);
      }
    } catch {
      // Layer not ready yet on this event; onStyleData/onLoad fire again.
    }
  }
}

export const GISMapContainer: React.FC = () => {
  const { layers, toggleVisibility, updateOpacity, toggleLegend, categoryFilters, toggleCategory, setAllCategories } =
    useLayerState();
  const visibleLayerIds = useMemo(
    () => layers.filter((lyr) => lyr.visible).map((lyr) => lyr.id),
    [layers]
  );
  const { datasets } = useGISData(visibleLayerIds);
  const trace = useNetworkTrace();
  const [hoverInfo, setHoverInfo] = useState<any>(null);
  const [pinnedInfo, setPinnedInfo] = useState<any>(null);
  const [investigateMode, setInvestigateMode] = useState<InvestigateMode>('owner');
  const [investigateQuery, setInvestigateQuery] = useState('');
  const [viewState, setViewState] = useState<Record<string, any>>(INITIAL_VIEW_STATE);
  const containerRef = useRef<HTMLDivElement>(null);
  const mapDimensionsRef = useRef({ width: window.innerWidth, height: window.innerHeight });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    // ResizeObserver reflects the actual DeckGL canvas size — window.innerWidth
    // /innerHeight measured the browser viewport, which doesn't always match
    // (e.g. devicePixelRatio/layout differences), throwing off fitBounds' zoom.
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      mapDimensionsRef.current = { width, height };
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Owner/NERC-region/state investigation and network trace are mutually
  // exclusive modes — starting one clears the others, so layerFactory only
  // ever has to reason about a single ActiveHighlight at a time.
  const handleInvestigateQueryChange = useCallback(
    (query: string) => {
      if (query && trace.active) trace.clearTrace();
      setInvestigateQuery(query);
    },
    [trace]
  );

  const handleInvestigateModeChange = useCallback((mode: InvestigateMode) => {
    setInvestigateMode(mode);
    setInvestigateQuery('');
  }, []);

  const handleTracePlant = useCallback(
    (layerId: TraceableLayerId, plantId: number, plantName: string) => {
      setInvestigateQuery('');
      setPinnedInfo(null);
      trace.startTrace(layerId, plantId, plantName);
    },
    [trace]
  );

  const handleFilterOwner = useCallback(
    (owner: string) => {
      if (trace.active) trace.clearTrace();
      setInvestigateMode('owner');
      setInvestigateQuery(owner);
      setPinnedInfo(null);
    },
    [trace]
  );

  const handleFilterNercRegion = useCallback(
    (subregionName: string) => {
      if (trace.active) trace.clearTrace();
      setInvestigateMode('nerc-region');
      setInvestigateQuery(subregionName);
      setPinnedInfo(null);
    },
    [trace]
  );

  const handleFilterState = useCallback(
    (state: string) => {
      if (trace.active) trace.clearTrace();
      setInvestigateMode('state');
      setInvestigateQuery(state);
      setPinnedInfo(null);
    },
    [trace]
  );

  const { highlight, highlightVersion }: { highlight: ActiveHighlight | null; highlightVersion: string | number } =
    useMemo(() => {
      if (trace.active) {
        const homeSubregion = trace.result?.status === 'ok' ? trace.result.home_subregion : null;
        return {
          highlight: createTraceHighlight(trace.sourceLayerId!, trace.plantId!, trace.revealedLineIds, homeSubregion),
          highlightVersion: trace.revealedMiles,
        };
      }
      const config =
        investigateMode === 'nerc-region'
          ? NERC_REGION_SEARCH
          : investigateMode === 'state'
          ? STATE_SEARCH
          : investigateMode === 'process'
          ? PROCESS_SEARCH
          : investigateMode === 'defense-history'
          ? DEFENSE_WORK_SEARCH
          : null;
      const investigateHighlight = config
        ? createAttributeHighlight(config, investigateQuery)
        : createOwnerHighlight(investigateQuery);
      return { highlight: investigateHighlight, highlightVersion: `${investigateMode}:${investigateQuery}` };
    }, [
      trace.active,
      trace.sourceLayerId,
      trace.plantId,
      trace.revealedLineIds,
      trace.revealedMiles,
      trace.result,
      investigateMode,
      investigateQuery,
    ]);

  const deckLayers = useMemo(
    () => createDeckGLLayers(layers, datasets, categoryFilters, highlight, highlightVersion, setHoverInfo),
    [layers, datasets, categoryFilters, highlight, highlightVersion]
  );

  // Flies the camera to whatever the current investigate query matches —
  // debounced so free-text owner search doesn't yank the map on every
  // keystroke, only once typing settles. Trace mode manages its own camera
  // via revealed lines, so this only applies to investigate.
  useEffect(() => {
    if (trace.active || !investigateQuery.trim()) return;
    const timer = window.setTimeout(() => {
      const bounds = computeMatchedBounds(datasets, highlight!);
      if (!bounds) return;
      const { width, height } = mapDimensionsRef.current;
      const viewport = new WebMercatorViewport({ width, height });
      // Proportional (not fixed-pixel) padding — a fixed value like 120px
      // eats a huge share of a narrow/embedded viewport's target area,
      // under-zooming the result far more than intended on smaller screens.
      const paddingX = width * 0.12;
      const paddingY = height * 0.12;
      const { longitude, latitude, zoom } = viewport.fitBounds(
        [
          [bounds[0], bounds[1]],
          [bounds[2], bounds[3]],
        ],
        { padding: { top: paddingY, bottom: paddingY, left: paddingX, right: paddingX }, maxZoom: 12 }
      );
      setViewState((prev) => ({
        ...prev,
        longitude,
        latitude,
        zoom,
        // fitBounds computes for a flat top-down projection — with the
        // map's default pitch left in place, the tilt makes the fitted
        // area appear to overshoot past the actual target on screen, so
        // level the camera for an accurate view of the investigate area.
        pitch: 0,
        bearing: 0,
        transitionDuration: 800,
        transitionInterpolator: new FlyToInterpolator(),
      }));
    }, 400);
    return () => window.clearTimeout(timer);
  }, [investigateMode, investigateQuery, datasets, highlight, trace.active]);

  return (
    <div ref={containerRef} className="relative h-screen w-screen overflow-hidden bg-slate-950">
      <LayerManager
        layers={layers}
        onToggle={toggleVisibility}
        onOpacityChange={updateOpacity}
        onToggleLegend={toggleLegend}
        categoryFilters={categoryFilters}
        onToggleCategory={toggleCategory}
        onSetAllCategories={setAllCategories}
      />

      {trace.active ? (
        <TracePanel
          plantName={trace.plantName}
          loading={trace.loading}
          result={trace.result}
          revealedMiles={trace.revealedMiles}
          maxDistance={trace.maxDistance}
          maxMiles={trace.maxMiles}
          playing={trace.playing}
          onTogglePlay={trace.togglePlay}
          onTraceFurther={trace.traceFurther}
          onClear={trace.clearTrace}
        />
      ) : (
        <InvestigatePanel
          layers={layers}
          datasets={datasets}
          mode={investigateMode}
          onModeChange={handleInvestigateModeChange}
          query={investigateQuery}
          onQueryChange={handleInvestigateQueryChange}
        />
      )}

      <DeckGL
        viewState={viewState}
        onViewStateChange={({ viewState: next }) => setViewState(next)}
        controller={true}
        layers={deckLayers}
        getCursor={({ isHovering }) => (isHovering ? 'pointer' : 'default')}
        onClick={(info) => setPinnedInfo(info?.object ? info : null)}
      >
        <Map
          mapboxAccessToken={MAPBOX_TOKEN}
          mapStyle="mapbox://styles/mapbox/dark-v11"
          // Mercator, not globe: deck.gl's GeoJsonLayer overlay (below) is
          // always flat-Mercator-projected regardless of the basemap's
          // projection — it has no concept of the globe's curvature. Mapbox
          // interpolates globe -> mercator between zoom 3-5, and this app's
          // default zoom (4) sits right in that band, so a globe projection
          // here made every data layer visibly float above/misalign with
          // the curved basemap. Mercator keeps both flat at every zoom.
          projection={{ name: 'mercator' }}
          reuseMaps
          onLoad={recolorBasemap}
          onStyleData={recolorBasemap}
        />
      </DeckGL>

      {!pinnedInfo && hoverInfo?.object && (
        <FeatureTooltip
          x={hoverInfo.x}
          y={hoverInfo.y}
          layerId={hoverInfo.layer?.id ?? ''}
          properties={hoverInfo.object.properties}
        />
      )}

      {pinnedInfo?.object && (
        <FeatureTooltip
          x={pinnedInfo.x}
          y={pinnedInfo.y}
          layerId={pinnedInfo.layer?.id ?? ''}
          properties={pinnedInfo.object.properties}
          pinned
          onFilterOwner={handleFilterOwner}
          onFilterNercRegion={handleFilterNercRegion}
          onFilterState={handleFilterState}
          onTracePlant={handleTracePlant}
          onClose={() => setPinnedInfo(null)}
        />
      )}

      <AdminControls />
    </div>
  );
};
