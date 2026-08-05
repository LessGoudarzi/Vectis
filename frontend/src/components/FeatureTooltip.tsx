import React from 'react';
import { X, Zap } from 'lucide-react';
import { LayerId } from '../types/gis';
import { getFeatureOwners } from '../owners';
import { STATE_SEARCH } from '../attributeSearch';
import { TraceableLayerId } from '../networkTrace';

const TRACEABLE_LAYERS = new Set<string>(['power-plants', 'auto-plants']);

interface FeatureTooltipProps {
  x: number;
  y: number;
  layerId: string;
  properties: Record<string, any>;
  // Hover tooltips (pinned=false) are transient and can't hold clickable
  // actions — the cursor leaving the feature to reach a button would hide
  // them first. Click promotes a feature to "pinned": it stays open and
  // pointer-events-auto, so the owner-filter and trace buttons are
  // actually usable.
  pinned?: boolean;
  onFilterOwner?: (owner: string) => void;
  onFilterNercRegion?: (subregionName: string) => void;
  onFilterState?: (state: string) => void;
  onTracePlant?: (layerId: TraceableLayerId, facilityId: number, facilityName: string) => void;
  onClose?: () => void;
}

// `geom` duplicates the feature's own geometry as a WKT string (DuckDB's
// to_json(t) serializes every column, geometry included) — noise in a
// property list meant for humans.
const HIDDEN_KEYS = new Set(['geom']);

// GEM tool datasets use -999999 as a "no value" sentinel for numeric
// fields (voltage, capacity, etc.) instead of null.
const MISSING_NUMBER_SENTINEL = -999999;

// Overrides for keys whose mechanical title-casing reads poorly —
// source_des in particular ("Source Des") doesn't convey that it's the
// full multi-fuel breakdown (e.g. "Coal = 458 MW, Solar = 12.5 MW"),
// unlike fuel_type which is just the single dominant bucket.
const KEY_LABELS: Record<string, string> = {
  source_des: 'Fuel Sources',
};

function toTitleCase(key: string): string {
  if (KEY_LABELS[key]) return KEY_LABELS[key];
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (Array.isArray(value)) return value.length > 0 ? value.join(', ') : '—';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') {
    if (value === MISSING_NUMBER_SENTINEL) return 'Unknown';
    if (key.endsWith('_usd')) return `$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
    if (key.endsWith('_pct')) return `${value.toLocaleString()}%`;
    if (key.endsWith('_kv')) return `${value.toLocaleString()} kV`;
    if (key.endsWith('_kw')) return `${value.toLocaleString()} kW`;
    if (key.endsWith('_mw')) return `${value.toLocaleString()} MW`;
    return value.toLocaleString();
  }
  return String(value);
}

export const FeatureTooltip: React.FC<FeatureTooltipProps> = ({
  x,
  y,
  layerId,
  properties,
  pinned = false,
  onFilterOwner,
  onFilterNercRegion,
  onFilterState,
  onTracePlant,
  onClose,
}) => {
  const entries = Object.entries(properties ?? {}).filter(([key]) => !HIDDEN_KEYS.has(key));
  const owners = pinned ? getFeatureOwners(layerId as LayerId, properties) : [];
  const subregionName: string | null = pinned ? properties?.subregion_name ?? null : null;
  const rawState: string | null = pinned ? properties?.state ?? null : null;
  const state = rawState && !STATE_SEARCH.invalidValues?.has(rawState) ? rawState : null;
  const canTrace = pinned && TRACEABLE_LAYERS.has(layerId) && onTracePlant && properties?.id != null;
  const facilityName = properties?.plant_name ?? properties?.facility_name ?? 'Unnamed Facility';

  return (
    <div
      className={`absolute z-30 flex max-h-72 max-w-xs flex-col overflow-hidden rounded-lg border text-xs text-white shadow-xl backdrop-blur-md ${
        pinned
          ? 'pointer-events-auto border-cyan-500/60 bg-slate-900'
          : 'pointer-events-none border-slate-700 bg-slate-900/95'
      }`}
      style={{ left: x + 12, top: y + 12 }}
    >
      <div className="flex shrink-0 items-center justify-between border-b border-slate-700/60 p-3 pb-1.5">
        <span className="text-[11px] font-bold uppercase tracking-wide text-cyan-400">
          {layerId.replace(/-/g, ' ')}
        </span>
        {pinned && onClose && (
          <button onClick={onClose} className="text-slate-400 hover:text-white" title="Close">
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {/* Actions come before the (potentially long) property list — some
          layers carry a long free-text field (e.g. auto-plants'
          conversion_summary) that would otherwise push these buttons out
          of view without scrolling. */}
      {canTrace && (
        <div className="shrink-0 px-3 pt-2">
          <button
            onClick={() => onTracePlant!(layerId as TraceableLayerId, properties.id, facilityName)}
            className="flex w-full items-center justify-center gap-1.5 rounded bg-cyan-500/15 px-2 py-1.5 text-[11px] font-medium text-cyan-300 hover:bg-cyan-500/25"
          >
            <Zap className="h-3 w-3" />
            Trace Network
          </button>
        </div>
      )}

      {owners.length > 0 && onFilterOwner && (
        <div className="shrink-0 space-y-1 px-3 pt-2">
          {owners.map((owner) => (
            <button
              key={owner}
              onClick={() => onFilterOwner(owner)}
              className="block w-full truncate rounded bg-cyan-500/15 px-2 py-1 text-left text-[11px] font-medium text-cyan-300 hover:bg-cyan-500/25"
            >
              Filter to: {owner}
            </button>
          ))}
        </div>
      )}

      {subregionName && onFilterNercRegion && (
        <div className="shrink-0 px-3 pt-2">
          <button
            onClick={() => onFilterNercRegion(subregionName)}
            className="block w-full truncate rounded bg-cyan-500/15 px-2 py-1 text-left text-[11px] font-medium text-cyan-300 hover:bg-cyan-500/25"
          >
            Filter to NERC region: {subregionName}
          </button>
        </div>
      )}

      {state && onFilterState && (
        <div className="shrink-0 px-3 pt-2">
          <button
            onClick={() => onFilterState(state)}
            className="block w-full truncate rounded bg-cyan-500/15 px-2 py-1 text-left text-[11px] font-medium text-cyan-300 hover:bg-cyan-500/25"
          >
            Filter to state: {state}
          </button>
        </div>
      )}

      <dl className="grid min-h-0 flex-1 grid-cols-[auto_1fr] gap-x-3 gap-y-1 overflow-y-auto p-3 pt-2">
        {entries.map(([key, value]) => (
          <React.Fragment key={key}>
            <dt className="text-slate-400">{toTitleCase(key)}</dt>
            <dd className="text-right font-mono text-slate-200">{formatValue(key, value)}</dd>
          </React.Fragment>
        ))}
      </dl>
    </div>
  );
};
