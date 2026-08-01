import { GeoJsonLayer } from '@deck.gl/layers';
import { LayerConfig, LayerId } from '../types/gis';
import { IndustrialConvergenceProperties, PowerPlantProperties, TransmissionLineProperties } from '../types/gis';
import { fuelColorHex, voltageBucketColorHex, getFeatureCategoryLabel } from '../legends';

const hexToRgb = (hex: string): [number, number, number] => {
  const num = parseInt(hex.replace('#', ''), 16);
  return [(num >> 16) & 255, (num >> 8) & 255, num & 255];
};

const BOTTLENECK_COLOR: [number, number, number] = [239, 68, 68]; // red-500, flags an energy-constrained facility

function filterByActiveCategories(layerId: LayerId, data: any, activeCategories: Set<string>) {
  if (!data?.features) return data;
  return {
    ...data,
    features: data.features.filter((f: any) =>
      activeCategories.has(getFeatureCategoryLabel(layerId, f.properties))
    ),
  };
}

export function createDeckGLLayers(
  configs: LayerConfig[],
  datasets: Record<string, any>,
  categoryFilters: Record<LayerId, Set<string>>,
  onHover: (info: any) => void
) {
  const sorted = [...configs].sort((a, b) => a.zIndex - b.zIndex);

  return sorted
    .filter((config) => config.visible)
    .map((config) => {
      const rgb = hexToRgb(config.colorHex);
      const rawData = datasets[config.id];
      if (!rawData) return null;
      const data = filterByActiveCategories(config.id, rawData, categoryFilters[config.id]);

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
            // Colored by voltage bucket (see legends.ts / the Legend toggle
            // in the layer panel), not the layer's flat swatch color.
            getLineColor: (f: any) => {
              const props = f.properties as TransmissionLineProperties;
              return [...hexToRgb(voltageBucketColorHex(props.voltage)), 220];
            },
            getLineWidth: (f: any) => {
              const props = f.properties as TransmissionLineProperties;
              return props.voltage != null && props.voltage >= 345 ? 4 : 2;
            },
            lineWidthMinPixels: 2,
            updateTriggers: {
              getLineColor: [config.id],
              getLineWidth: [config.id],
            },
            onHover,
          });

        case 'power-plants':
          return new GeoJsonLayer({
            id: config.id,
            data,
            pickable: true,
            opacity: config.opacity,
            pointRadiusUnits: 'meters',
            pointRadiusScale: 1,
            getPointRadius: (f: any) => {
              const props = f.properties as PowerPlantProperties;
              // sqrt scaling so gigawatt-scale plants don't swamp the map
              return 2000 + Math.sqrt(Math.max(props.capacity_mw ?? 0, 0)) * 150;
            },
            pointRadiusMinPixels: 3,
            pointRadiusMaxPixels: 30,
            getFillColor: (f: any) => {
              const props = f.properties as PowerPlantProperties;
              return [...hexToRgb(fuelColorHex(props.fuel_type)), 200];
            },
            getLineColor: [255, 255, 255, 180],
            getLineWidth: 1,
            lineWidthMinPixels: 1,
            onHover,
          });

        case 'industrial-convergence':
          return new GeoJsonLayer({
            id: config.id,
            data,
            pickable: true,
            opacity: config.opacity,
            pointRadiusUnits: 'meters',
            pointRadiusScale: 1,
            getPointRadius: (f: any) => {
              const props = f.properties as IndustrialConvergenceProperties;
              const output = props.estimated_annual_output_usd ?? 0;
              // sqrt scaling keeps the largest facilities from swamping the map
              return 3000 + Math.sqrt(output) * 2;
            },
            pointRadiusMinPixels: 5,
            pointRadiusMaxPixels: 40,
            getFillColor: (f: any) => {
              const props = f.properties as IndustrialConvergenceProperties;
              return props.energy_bottleneck_flag ? [...BOTTLENECK_COLOR, 220] : [...rgb, 220];
            },
            getLineColor: [255, 255, 255, 255],
            getLineWidth: 2,
            lineWidthMinPixels: 1,
            onHover,
          });

        default:
          return null;
      }
    })
    .filter(Boolean);
}
