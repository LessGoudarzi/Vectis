import React from 'react';

interface FeatureTooltipProps {
  x: number;
  y: number;
  layerId: string;
  properties: Record<string, any>;
}

// `geom` duplicates the feature's own geometry as a WKT string (DuckDB's
// to_json(t) serializes every column, geometry included) — noise in a
// property list meant for humans.
const HIDDEN_KEYS = new Set(['geom']);

// GEM tool datasets use -999999 as a "no value" sentinel for numeric
// fields (voltage, capacity, etc.) instead of null.
const MISSING_NUMBER_SENTINEL = -999999;

function toTitleCase(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
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

export const FeatureTooltip: React.FC<FeatureTooltipProps> = ({ x, y, layerId, properties }) => {
  const entries = Object.entries(properties ?? {}).filter(([key]) => !HIDDEN_KEYS.has(key));

  return (
    <div
      className="absolute z-30 pointer-events-none max-w-xs rounded-lg border border-slate-700 bg-slate-900/95 p-3 text-xs text-white shadow-xl backdrop-blur-md"
      style={{ left: x + 12, top: y + 12 }}
    >
      <div className="mb-1.5 border-b border-slate-700/60 pb-1.5 text-[11px] font-bold uppercase tracking-wide text-cyan-400">
        {layerId.replace(/-/g, ' ')}
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
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
