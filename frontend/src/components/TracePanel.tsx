import React from 'react';
import { Zap, Pause, Play, X } from 'lucide-react';
import { TraceResult } from '../networkTrace';

interface TracePanelProps {
  plantName: string | null;
  loading: boolean;
  result: TraceResult | null;
  revealedMiles: number;
  maxDistance: number;
  maxMiles: number;
  playing: boolean;
  onTogglePlay: () => void;
  onTraceFurther: () => void;
  onClear: () => void;
}

function stoppedReasonMessage(result: TraceResult, maxMiles: number): string {
  switch (result.stopped_reason) {
    case 'max_miles':
      return `Reached the ${maxMiles}mi trace limit — Trace Further to continue.`;
    case 'subregion_boundary':
      return `Reached the edge of the ${result.home_subregion ?? 'home'} subregion — Trace Further to cross into neighboring subregions.`;
    case 'component_exhausted':
      return 'Reached the end of the connected network.';
    default:
      return '';
  }
}

export const TracePanel: React.FC<TracePanelProps> = ({
  plantName,
  loading,
  result,
  revealedMiles,
  maxDistance,
  maxMiles,
  playing,
  onTogglePlay,
  onTraceFurther,
  onClear,
}) => {
  const progressPct = maxDistance > 0 ? Math.min(100, (revealedMiles / maxDistance) * 100) : 0;
  const canTraceFurther = result?.status === 'ok' && result.stopped_reason !== 'component_exhausted';
  const canPlayPause = result?.status === 'ok' && revealedMiles < maxDistance;

  return (
    <div className="absolute top-4 right-4 z-20 w-80 rounded-xl border border-cyan-500/40 bg-slate-900/90 p-4 shadow-2xl backdrop-blur-md text-slate-100">
      <div className="mb-1 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Zap className="h-4 w-4 text-cyan-400" />
          <h2 className="text-sm font-semibold uppercase tracking-wider">Network Trace</h2>
        </div>
        <button onClick={onClear} className="text-slate-400 hover:text-white" title="Clear trace">
          <X className="h-4 w-4" />
        </button>
      </div>
      <p className="mb-3 truncate text-xs font-medium text-cyan-300">{plantName}</p>

      {loading && <p className="text-[11px] text-slate-400">Tracing network...</p>}

      {!loading && result?.status === 'not_connected' && (
        <p className="text-[11px] text-slate-400">
          No transmission connection found within 2 miles of this facility.
        </p>
      )}
      {!loading && result?.status === 'not_found' && (
        <p className="text-[11px] text-slate-400">Facility not found.</p>
      )}
      {!loading && result?.status === 'unavailable' && (
        <p className="text-[11px] text-slate-400">
          {result.detail ?? 'Grid topology not built yet — run power/build_grid_topology.py.'}
        </p>
      )}

      {!loading && result?.status === 'ok' && (
        <>
          <p className="mb-2 text-[10px] text-slate-400">
            Home subregion: <span className="text-slate-300">{result.home_subregion ?? 'Unknown'}</span>
          </p>

          <div className="mb-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-700">
            <div
              className="h-full bg-cyan-400 transition-[width] duration-100 ease-linear"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          <p className="mb-3 text-[10px] font-mono text-slate-400">
            {revealedMiles.toFixed(0)} / {maxDistance.toFixed(0)} mi revealed
          </p>

          <p className="mb-3 text-[10px] text-slate-500">{stoppedReasonMessage(result, maxMiles)}</p>

          <div className="flex items-center gap-2">
            {canPlayPause && (
              <button
                onClick={onTogglePlay}
                className="flex items-center gap-1 rounded bg-slate-700/60 px-2.5 py-1 text-[11px] font-medium text-slate-200 hover:bg-slate-700"
              >
                {playing ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />}
                {playing ? 'Pause' : 'Play'}
              </button>
            )}
            {canTraceFurther && (
              <button
                onClick={onTraceFurther}
                className="rounded bg-cyan-500/20 px-2.5 py-1 text-[11px] font-medium text-cyan-300 hover:bg-cyan-500/30"
              >
                Trace Further
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
};
