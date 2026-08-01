import { useState, useCallback } from 'react';
import { LayerConfig, LayerId } from '../types/gis';
import { LAYER_LEGENDS } from '../legends';

export const INITIAL_LAYERS: LayerConfig[] = [
  { id: 'power-grid', name: 'Transmission Lines', visible: true, opacity: 0.8, colorHex: '#06B6D4', zIndex: 1, legendVisible: true },
  { id: 'substations', name: 'Substations', visible: true, opacity: 0.9, colorHex: '#FBBF24', zIndex: 2, legendVisible: true },
  { id: 'auto-plants', name: 'Automobile Manufacturing Facilities', visible: true, opacity: 0.9, colorHex: '#F59E0B', zIndex: 3, legendVisible: true },
  { id: 'power-plants', name: 'Power Plants', visible: true, opacity: 0.9, colorHex: '#22C55E', zIndex: 4, legendVisible: true },
  { id: 'industrial-convergence', name: 'Industrial Convergence Facilities', visible: true, opacity: 0.9, colorHex: '#A855F7', zIndex: 5, legendVisible: false },
];

function allCategoryLabels(id: LayerId): Set<string> {
  return new Set(LAYER_LEGENDS[id].map((entry) => entry.label));
}

const INITIAL_CATEGORY_FILTERS: Record<LayerId, Set<string>> = Object.fromEntries(
  INITIAL_LAYERS.map((lyr) => [lyr.id, allCategoryLabels(lyr.id)])
) as Record<LayerId, Set<string>>;

export function useLayerState() {
  const [layers, setLayers] = useState<LayerConfig[]>(INITIAL_LAYERS);
  const [categoryFilters, setCategoryFilters] = useState<Record<LayerId, Set<string>>>(INITIAL_CATEGORY_FILTERS);

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

  const toggleLegend = useCallback((id: LayerId) => {
    setLayers((prev) =>
      prev.map((lyr) => (lyr.id === id ? { ...lyr, legendVisible: !lyr.legendVisible } : lyr))
    );
  }, []);

  const toggleCategory = useCallback((id: LayerId, label: string) => {
    setCategoryFilters((prev) => {
      const next = new Set(prev[id]);
      if (next.has(label)) {
        next.delete(label);
      } else {
        next.add(label);
      }
      return { ...prev, [id]: next };
    });
  }, []);

  const setAllCategories = useCallback((id: LayerId, active: boolean) => {
    setCategoryFilters((prev) => ({
      ...prev,
      [id]: active ? allCategoryLabels(id) : new Set<string>(),
    }));
  }, []);

  return {
    layers,
    toggleVisibility,
    updateOpacity,
    toggleLegend,
    categoryFilters,
    toggleCategory,
    setAllCategories,
  };
}
