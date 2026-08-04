import { GeoJsonLayer } from '@deck.gl/layers';
import { ActiveHighlight, LayerConfig, LayerId } from '../types/gis';
import { PowerPlantProperties, TransmissionLineProperties, SubstationProperties, AutoPlantProperties, NercSubregionProperties } from '../types/gis';
import { fuelColorHex, voltageBucketColorHex, autoPlantColorHex, nercRegionColorHex, getFeatureCategoryLabel } from '../legends';

const hexToRgb = (hex: string): [number, number, number] => {
  const num = parseInt(hex.replace('#', ''), 16);
  return [(num >> 16) & 255, (num >> 8) & 255, num & 255];
};

// Solid white square, tinted per-feature via getIconColor (mask: true treats
// the image as a single-channel alpha mask rather than fixed RGB).
const SQUARE_ICON = {
  url: 'data:image/svg+xml;base64,' + btoa('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10" fill="white"/></svg>'),
  width: 10,
  height: 10,
  mask: true,
};

function filterByActiveCategories(layerId: LayerId, data: any, activeCategories: Set<string>) {
  if (!data?.features) return data;
  return {
    ...data,
    features: data.features.filter((f: any) =>
      activeCategories.has(getFeatureCategoryLabel(layerId, f.properties))
    ),
  };
}

// When an investigative highlight is active (owner search or network
// trace — see types/gis.ts's ActiveHighlight): matches always get
// boosted alpha; exempt features (e.g. network trace's "same home
// subregion" features) hold their normal alpha; everything else dims.
function highlightAlpha(baseAlpha: number, isMatch: boolean, isExempt: boolean, highlightActive: boolean): number {
  if (!highlightActive) return baseAlpha;
  if (isMatch) return Math.min(255, baseAlpha + 25);
  return isExempt ? baseAlpha : Math.round(baseAlpha * 0.12);
}

export function createDeckGLLayers(
  configs: LayerConfig[],
  datasets: Record<string, any>,
  categoryFilters: Record<LayerId, Set<string>>,
  highlight: ActiveHighlight | null,
  highlightVersion: string | number,
  onHover: (info: any) => void
) {
  const sorted = [...configs].sort((a, b) => a.zIndex - b.zIndex);
  const highlightActive = highlight != null;

  return sorted
    .filter((config) => config.visible)
    .map((config) => {
      const rawData = datasets[config.id];
      if (!rawData) return null;
      const data = filterByActiveCategories(config.id, rawData, categoryFilters[config.id]);
      const isMatch = (f: any) => highlight?.isMatch(config.id, f.properties) ?? false;
      const isExempt = (f: any) => highlight?.isExempt?.(config.id, f.properties) ?? false;
      const colorOverride = highlight?.colorOverrideHex?.[config.id];
      const colorOverrideRgb = colorOverride ? hexToRgb(colorOverride) : null;

      switch (config.id) {
        case 'auto-plants':
          return new GeoJsonLayer({
            id: config.id,
            data,
            pickable: true,
            opacity: config.opacity,
            // Colored by facility_type (see legends.ts's AUTO_PLANTS_LEGEND) —
            // Assembly / Battery / Engine / Transmission / Body-Stamping /
            // Other Major Component, matching the real data's categories.
            pointType: 'icon',
            getIcon: () => SQUARE_ICON,
            iconSizeUnits: 'pixels',
            getIconSize: 6,
            iconSizeMinPixels: 6,
            iconSizeMaxPixels: 6,
            getIconColor: (f: any) => {
              const props = f.properties as AutoPlantProperties;
              return [...hexToRgb(autoPlantColorHex(props.facility_type)), highlightAlpha(220, isMatch(f), isExempt(f), highlightActive)];
            },
            updateTriggers: { getIconColor: [highlightVersion] },
            onHover,
          });

        case 'power-grid':
          return new GeoJsonLayer({
            id: config.id,
            data,
            pickable: true,
            opacity: config.opacity,
            // Colored by voltage bucket (see legends.ts / the Legend toggle
            // in the layer panel) unless a network trace overrides matching
            // lines to an "energized" highlight color instead.
            //
            // Deliberately ignores isExempt (unlike the other data layers
            // below): the trace's whole point is lines lighting up as the
            // reveal wave moves outward, which only reads as an animation
            // if not-yet-revealed lines are dim — showing every in-subregion
            // line at near-full brightness from frame one (as isExempt
            // would) flattens that contrast to nothing.
            getLineColor: (f: any) => {
              const props = f.properties as TransmissionLineProperties;
              const match = isMatch(f);
              const baseColor = match && colorOverrideRgb ? colorOverrideRgb : hexToRgb(voltageBucketColorHex(props.voltage));
              return [...baseColor, highlightAlpha(220, match, false, highlightActive)];
            },
            getLineWidth: (f: any) => {
              const props = f.properties as TransmissionLineProperties;
              const baseWidth = props.voltage != null && props.voltage >= 345 ? 4 : 2;
              return highlightActive && isMatch(f) ? baseWidth + 1 : baseWidth;
            },
            lineWidthMinPixels: 2,
            updateTriggers: {
              getLineColor: [highlightVersion],
              getLineWidth: [highlightVersion],
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
              return [...hexToRgb(fuelColorHex(props.fuel_type)), highlightAlpha(200, isMatch(f), isExempt(f), highlightActive)];
            },
            getLineColor: (f: any) => [255, 255, 255, highlightAlpha(180, isMatch(f), isExempt(f), highlightActive)],
            getLineWidth: 1,
            lineWidthMinPixels: 1,
            updateTriggers: { getFillColor: [highlightVersion], getLineColor: [highlightVersion] },
            onHover,
          });

        case 'substations':
          return new GeoJsonLayer({
            id: config.id,
            data,
            pickable: true,
            opacity: config.opacity,
            pointRadiusUnits: 'meters',
            pointRadiusScale: 1,
            // Colored by max_voltage_kv, same buckets/palette as
            // Transmission Lines (see legends.ts's VOLTAGE_LEGEND); sized
            // by line_count as a secondary "how significant a hub" cue.
            getPointRadius: (f: any) => {
              const props = f.properties as SubstationProperties;
              return 1500 + Math.sqrt(Math.max(props.line_count ?? 0, 0)) * 400;
            },
            pointRadiusMinPixels: 2,
            pointRadiusMaxPixels: 14,
            getFillColor: (f: any) => {
              const props = f.properties as SubstationProperties;
              return [...hexToRgb(voltageBucketColorHex(props.max_voltage_kv)), highlightAlpha(210, isMatch(f), isExempt(f), highlightActive)];
            },
            getLineColor: (f: any) => [255, 255, 255, highlightAlpha(160, isMatch(f), isExempt(f), highlightActive)],
            getLineWidth: 1,
            lineWidthMinPixels: 1,
            updateTriggers: { getFillColor: [highlightVersion], getLineColor: [highlightVersion] },
            onHover,
          });

        case 'nerc-subregions':
          return new GeoJsonLayer({
            id: config.id,
            data,
            // Not pickable: this is a giant background polygon covering the
            // whole map at the bottom of the stack — leaving it pickable
            // meant any click that missed a small point marker above it
            // (e.g. auto-plants' 8px dots) fell through to this layer
            // instead, pinning a tooltip with no useful actions.
            pickable: false,
            opacity: config.opacity,
            // Background context, not data — kept deliberately faint so it
            // never competes with the layers on top of it. A network trace
            // (see networkTrace.ts's createTraceHighlight) brightens just
            // the plant's home subregion, showing exactly where the trace
            // stopped rather than an arbitrary mileage figure.
            filled: true,
            stroked: true,
            lineWidthUnits: 'pixels',
            getFillColor: (f: any) => {
              const props = f.properties as NercSubregionProperties;
              const match = isMatch(f);
              const base = highlightActive ? (match ? 45 : 6) : 18;
              return [...hexToRgb(nercRegionColorHex(props.nerc_region)), base];
            },
            getLineColor: (f: any) => {
              const props = f.properties as NercSubregionProperties;
              const match = isMatch(f);
              const baseColor = match && colorOverrideRgb ? colorOverrideRgb : hexToRgb(nercRegionColorHex(props.nerc_region));
              return [...baseColor, highlightAlpha(140, match, false, highlightActive)];
            },
            getLineWidth: (f: any) => (highlightActive && isMatch(f) ? 3 : 1),
            updateTriggers: {
              getFillColor: [highlightVersion],
              getLineColor: [highlightVersion],
              getLineWidth: [highlightVersion],
            },
          });

        default:
          return null;
      }
    })
    .filter(Boolean);
}
