import React, { useMemo, useState } from 'react';
import { Search, X } from 'lucide-react';
import { LayerConfig, LayerId } from '../types/gis';
import { collectDistinctOwners, countMatchesByLayer } from '../owners';

interface OwnerSearchProps {
  layers: LayerConfig[];
  datasets: Record<string, any>;
  query: string;
  onQueryChange: (query: string) => void;
}

const MAX_SUGGESTIONS = 8;

export const OwnerSearch: React.FC<OwnerSearchProps> = ({ layers, datasets, query, onQueryChange }) => {
  const [focused, setFocused] = useState(false);
  const layerName = useMemo(
    () => Object.fromEntries(layers.map((l) => [l.id, l.name])) as Record<LayerId, string>,
    [layers]
  );

  // Recomputed only when the underlying data changes, not per keystroke —
  // all layer data is already in the browser (useGISData.ts), so this is
  // a client-side scan rather than a network round-trip.
  const distinctOwners = useMemo(() => collectDistinctOwners(datasets), [datasets]);

  const trimmed = query.trim();
  const suggestions = useMemo(() => {
    if (!trimmed) return [];
    const needle = trimmed.toLowerCase();
    return distinctOwners.filter((o) => o.toLowerCase().includes(needle)).slice(0, MAX_SUGGESTIONS);
  }, [distinctOwners, trimmed]);

  const matchCounts = useMemo(() => (trimmed ? countMatchesByLayer(datasets, trimmed) : {}), [datasets, trimmed]);
  const totalMatches = Object.values(matchCounts).reduce((sum, n) => sum + (n ?? 0), 0);

  const showDropdown = focused && trimmed.length > 0 && suggestions.length > 0;

  return (
    <div className="absolute top-4 right-4 z-20 w-80 rounded-xl border border-slate-700/50 bg-slate-900/80 p-4 shadow-2xl backdrop-blur-md text-slate-100">
      <div className="mb-1 flex items-center gap-2">
        <Search className="h-4 w-4 text-cyan-400" />
        <h2 className="text-sm font-semibold uppercase tracking-wider">Investigate Owner</h2>
      </div>
      <p className="mb-3 text-[10px] text-slate-400">
        Search across Transmission Lines, Power Plants, Substations (inferred), and Auto
        Facilities — matching features are highlighted, everything else dims.
      </p>

      <div className="relative">
        <input
          type="text"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setTimeout(() => setFocused(false), 150)}
          placeholder="e.g. Ford, Tennessee Valley Authority..."
          className="w-full rounded-lg border border-slate-600 bg-slate-800/80 px-3 py-1.5 text-xs text-white placeholder-slate-500 outline-none focus:border-cyan-400"
        />
        {query && (
          <button
            onClick={() => onQueryChange('')}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white"
            title="Clear"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}

        {showDropdown && (
          <div className="absolute left-0 right-0 top-full z-10 mt-1 max-h-48 overflow-y-auto rounded-lg border border-slate-700 bg-slate-800 shadow-xl">
            {suggestions.map((owner) => (
              <button
                key={owner}
                onMouseDown={() => onQueryChange(owner)}
                className="block w-full truncate px-3 py-1.5 text-left text-[11px] text-slate-200 hover:bg-slate-700"
              >
                {owner}
              </button>
            ))}
          </div>
        )}
      </div>

      {trimmed && (
        <div className="mt-3 border-t border-slate-700/40 pt-2">
          {totalMatches === 0 ? (
            <p className="text-[11px] text-slate-500">No matches.</p>
          ) : (
            <ul className="space-y-0.5">
              {(Object.keys(matchCounts) as LayerId[]).map((id) => (
                <li key={id} className="flex justify-between text-[11px]">
                  <span className="text-slate-400">{layerName[id]}</span>
                  <span className="font-mono text-cyan-400">{matchCounts[id]}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
};
