import React, { useState, useMemo } from 'react';
import DeckGL from '@deck.gl/react';
import { Map } from 'react-map-gl';
import { useLayerState } from '../hooks/useLayerState';
import { useGISData } from '../hooks/useGISData';
import { createDeckGLLayers } from '../layers/layerFactory';
import { LayerManager } from './LayerManager';
import { FeatureTooltip } from './FeatureTooltip';
import { OwnerSearch } from './OwnerSearch';
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
  const [pinnedInfo, setPinnedInfo] = useState<any>(null);
  const [ownerQuery, setOwnerQuery] = useState('');

  const deckLayers = useMemo(
    () => createDeckGLLayers(layers, datasets, categoryFilters, ownerQuery, setHoverInfo),
    [layers, datasets, categoryFilters, ownerQuery]
  );

  const handleFilterOwner = (owner: string) => {
    setOwnerQuery(owner);
    setPinnedInfo(null);
  };

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

      <OwnerSearch layers={layers} datasets={datasets} query={ownerQuery} onQueryChange={setOwnerQuery} />

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
          onClose={() => setPinnedInfo(null)}
        />
      )}
    </div>
  );
};
