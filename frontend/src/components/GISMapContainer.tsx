import React, { useState, useMemo } from 'react';
import DeckGL from '@deck.gl/react';
import { Map } from 'react-map-gl';
import { useLayerState } from '../hooks/useLayerState';
import { useGISData } from '../hooks/useGISData';
import { createDeckGLLayers } from '../layers/layerFactory';
import { LayerManager } from './LayerManager';
import { FeatureTooltip } from './FeatureTooltip';
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
        <FeatureTooltip
          x={hoverInfo.x}
          y={hoverInfo.y}
          layerId={hoverInfo.layer?.id ?? ''}
          properties={hoverInfo.object.properties}
        />
      )}
    </div>
  );
};
