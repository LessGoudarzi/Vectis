import React, { useState } from 'react';
import { LayerConfig, LayerId } from '../types/gis';
import { Eye, EyeOff, Sliders, List, ChevronLeft, ChevronRight } from 'lucide-react';
import { LAYER_LEGENDS } from '../legends';

interface LayerManagerProps {
  layers: LayerConfig[];
  onToggle: (id: LayerId) => void;
  onOpacityChange: (id: LayerId, value: number) => void;
  onToggleLegend: (id: LayerId) => void;
  categoryFilters: Record<LayerId, Set<string>>;
  onToggleCategory: (id: LayerId, label: string) => void;
  onSetAllCategories: (id: LayerId, active: boolean) => void;
}

export const LayerManager: React.FC<LayerManagerProps> = ({
  layers,
  onToggle,
  onOpacityChange,
  onToggleLegend,
  categoryFilters,
  onToggleCategory,
  onSetAllCategories,
}) => {
  const [collapsed, setCollapsed] = useState(false);
  const activeCount = layers.filter((l) => l.visible).length;

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        title="Expand layer control"
        className="absolute top-4 left-4 z-20 flex items-center gap-2 rounded-xl border border-slate-700/50 bg-slate-900/80 px-3 py-2.5 text-slate-100 shadow-2xl backdrop-blur-md hover:bg-slate-800"
      >
        <Sliders className="h-5 w-5 text-cyan-400" />
        <ChevronRight className="h-4 w-4 text-slate-400" />
      </button>
    );
  }

  return (
    <div className="absolute top-4 left-4 z-20 flex max-h-[calc(100vh-2rem)] w-80 flex-col rounded-xl border border-slate-700/50 bg-slate-900/80 p-4 shadow-2xl backdrop-blur-md text-slate-100">
      <div className="mb-4 flex shrink-0 items-center justify-between border-b border-slate-700/60 pb-3">
        <div className="flex items-center gap-2">
          <Sliders className="h-5 w-5 text-cyan-400" />
          <h2 className="font-semibold text-sm uppercase tracking-wider">Layer Control</h2>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-cyan-500/20 px-2.5 py-0.5 text-xs font-bold text-cyan-400 border border-cyan-500/30">
            {activeCount} / {layers.length} Active
          </span>
          <button
            onClick={() => setCollapsed(true)}
            title="Collapse layer control"
            className="rounded p-1 text-slate-400 hover:bg-slate-700 hover:text-white"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="space-y-3 overflow-y-auto pr-1">
        {layers.map((lyr) => {
          const legend = LAYER_LEGENDS[lyr.id];
          const active = categoryFilters[lyr.id] ?? new Set<string>();
          return (
            <div
              key={lyr.id}
              className={`rounded-lg border p-3 transition-all ${
                lyr.visible
                  ? 'border-slate-600 bg-slate-800/60'
                  : 'border-slate-800 bg-slate-950/40 opacity-60'
              }`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span
                    className="h-3 w-3 rounded-full border border-white/20"
                    style={{ backgroundColor: lyr.colorHex }}
                  />
                  <span className="text-xs font-medium text-slate-200">{lyr.name}</span>
                </div>

                <div className="flex items-center gap-1">
                  <button
                    onClick={() => onToggleLegend(lyr.id)}
                    title="Toggle legend"
                    aria-pressed={lyr.legendVisible}
                    className={`rounded p-1 hover:bg-slate-700 hover:text-white ${
                      lyr.legendVisible ? 'text-cyan-400' : 'text-slate-400'
                    }`}
                  >
                    <List className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => onToggle(lyr.id)}
                    className="rounded p-1 text-slate-400 hover:bg-slate-700 hover:text-white"
                  >
                    {lyr.visible ? <Eye className="h-4 w-4 text-cyan-400" /> : <EyeOff className="h-4 w-4" />}
                  </button>
                </div>
              </div>

              {lyr.visible && (
                <div className="mt-2.5 flex items-center gap-3 pt-2 border-t border-slate-700/40">
                  <span className="text-[10px] text-slate-400">Opacity</span>
                  <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.05"
                    value={lyr.opacity}
                    onChange={(e) => onOpacityChange(lyr.id, parseFloat(e.target.value))}
                    className="h-1 w-full cursor-pointer appearance-none rounded-lg bg-slate-700 accent-cyan-400"
                  />
                  <span className="text-[10px] text-slate-300 font-mono">
                    {Math.round(lyr.opacity * 100)}%
                  </span>
                </div>
              )}

              {lyr.legendVisible && legend && (
                <div className="mt-2.5 pt-2 border-t border-slate-700/40">
                  <div className="mb-1.5 flex items-center justify-between">
                    <span className="text-[10px] text-slate-400">
                      Click an item to show/hide it
                    </span>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => onSetAllCategories(lyr.id, true)}
                        className="rounded px-1.5 py-0.5 text-[10px] font-medium text-cyan-400 hover:bg-slate-700"
                      >
                        All
                      </button>
                      <span className="text-slate-600">/</span>
                      <button
                        onClick={() => onSetAllCategories(lyr.id, false)}
                        className="rounded px-1.5 py-0.5 text-[10px] font-medium text-slate-400 hover:bg-slate-700"
                      >
                        None
                      </button>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-1">
                    {legend.map((entry) => {
                      const isActive = active.has(entry.label);
                      return (
                        <button
                          key={entry.label}
                          onClick={() => onToggleCategory(lyr.id, entry.label)}
                          aria-pressed={isActive}
                          className={`flex items-center gap-1.5 rounded px-1 py-0.5 text-left hover:bg-slate-700/60 ${
                            isActive ? '' : 'opacity-40'
                          }`}
                        >
                          <span
                            className="h-2.5 w-2.5 shrink-0 rounded-full border border-white/20"
                            style={{ backgroundColor: entry.colorHex }}
                          />
                          <span
                            className={`truncate text-[10px] ${
                              isActive ? 'text-slate-300' : 'text-slate-500 line-through'
                            }`}
                          >
                            {entry.label}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
