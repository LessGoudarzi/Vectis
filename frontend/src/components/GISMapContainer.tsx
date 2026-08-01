import React, { useState, useMemo } from 'react';
import DeckGL from '@deck.gl/react';
import { Map } from 'react-map-gl';
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
  const { layers, toggleVisibility, updateOpacity, toggleLegend, categoryFilters, toggleCategory, setAllCategories } =
    useLayerState();
  const { datasets } = useGISData();
  const [hoverInfo, setHoverInfo] = useState<any>(null);

  const deckLayers = useMemo(
    () => createDeckGLLayers(layers, datasets, categoryFilters, setHoverInfo),
    [layers, datasets, categoryFilters]
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
