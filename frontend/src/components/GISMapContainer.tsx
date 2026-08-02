import React, { useState, useMemo, useCallback } from 'react';
import DeckGL from '@deck.gl/react';
import { Map } from 'react-map-gl';
import { useLayerState } from '../hooks/useLayerState';
import { useGISData } from '../hooks/useGISData';
import { useNetworkTrace } from '../hooks/useNetworkTrace';
import { createDeckGLLayers } from '../layers/layerFactory';
import { createOwnerHighlight } from '../owners';
import { createTraceHighlight, TraceableLayerId } from '../networkTrace';
import { ActiveHighlight } from '../types/gis';
import { LayerManager } from './LayerManager';
import { FeatureTooltip } from './FeatureTooltip';
import { OwnerSearch } from './OwnerSearch';
import { TracePanel } from './TracePanel';
import 'mapbox-gl/dist/mapbox-gl.css';

const INITIAL_VIEW_STATE = {
  longitude: -98.5795,
  latitude: 39.8283,
  zoom: 4,
  pitch: 35,
  bearing: 0,
};

const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN || '';

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
  const { datasets } = useGISData();
  const trace = useNetworkTrace();
  const [hoverInfo, setHoverInfo] = useState<any>(null);
  const [pinnedInfo, setPinnedInfo] = useState<any>(null);
  const [ownerQuery, setOwnerQuery] = useState('');

  // Owner search and network trace are mutually exclusive investigative
  // modes — starting one clears the other, so layerFactory only ever has
  // to reason about a single ActiveHighlight at a time.
  const handleOwnerQueryChange = useCallback(
    (query: string) => {
      if (query && trace.active) trace.clearTrace();
      setOwnerQuery(query);
    },
    [trace]
  );

  const handleTracePlant = useCallback(
    (layerId: TraceableLayerId, plantId: number, plantName: string) => {
      setOwnerQuery('');
      setPinnedInfo(null);
      trace.startTrace(layerId, plantId, plantName);
    },
    [trace]
  );

  const handleFilterOwner = useCallback(
    (owner: string) => {
      if (trace.active) trace.clearTrace();
      setOwnerQuery(owner);
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
      const ownerHighlight = createOwnerHighlight(ownerQuery);
      return { highlight: ownerHighlight, highlightVersion: ownerQuery };
    }, [trace.active, trace.sourceLayerId, trace.plantId, trace.revealedLineIds, trace.revealedMiles, trace.result, ownerQuery]);

  const deckLayers = useMemo(
    () => createDeckGLLayers(layers, datasets, categoryFilters, highlight, highlightVersion, setHoverInfo),
    [layers, datasets, categoryFilters, highlight, highlightVersion]
  );

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-slate-950">
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
        <OwnerSearch layers={layers} datasets={datasets} query={ownerQuery} onQueryChange={handleOwnerQueryChange} />
      )}

      <DeckGL
        initialViewState={INITIAL_VIEW_STATE}
        controller={true}
        layers={deckLayers}
        getCursor={({ isHovering }) => (isHovering ? 'pointer' : 'default')}
        onClick={(info) => setPinnedInfo(info?.object ? info : null)}
      >
        <Map
          mapboxAccessToken={MAPBOX_TOKEN}
          mapStyle="mapbox://styles/mapbox/dark-v11"
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
          onTracePlant={handleTracePlant}
          onClose={() => setPinnedInfo(null)}
        />
      )}
    </div>
  );
};
