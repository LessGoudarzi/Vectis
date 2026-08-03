import { useState, useEffect, useRef } from 'react';
import { LayerId } from '../types/gis';

const API_BASE = '/api/v1/layers';

// Fetches each layer's data lazily, the first time it's visible, rather
// than all five up front — auto-plants/power-grid are large enough that
// eagerly fetching them just to sit hidden behind an unchecked sidebar
// toggle was wasted work on every page load.
export function useGISData(visibleLayerIds: LayerId[]) {
  const [datasets, setDatasets] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState<boolean>(true);
  // Split into "in-flight promise" (deduped by id) and "loaded" (marked only
  // once data is actually in state) — React 18 StrictMode double-invokes
  // effects in dev (mount, cleanup, mount again). Marking a layer fetched
  // up front, before the request resolved, meant the first (real) fetch got
  // cancelled by the synchronous cleanup while the ref already blocked any
  // retry, so its data never made it into state. Reusing the in-flight
  // promise across both invocations avoids a duplicate request while still
  // letting whichever effect instance survives apply the result.
  const inFlightRef = useRef<Map<LayerId, Promise<any>>>(new Map());
  const loadedRef = useRef<Set<LayerId>>(new Set());

  useEffect(() => {
    const toFetch = visibleLayerIds.filter((id) => !loadedRef.current.has(id));
    if (toFetch.length === 0) {
      setLoading(false);
      return;
    }

    let cancelled = false;
    async function loadLayers() {
      try {
        const results = await Promise.all(
          toFetch.map((id) => {
            let pending = inFlightRef.current.get(id);
            if (!pending) {
              pending = fetch(`${API_BASE}/${id}`).then((res) => res.json());
              inFlightRef.current.set(id, pending);
            }
            return pending;
          })
        );
        if (cancelled) return;
        setDatasets((prev) => {
          const next = { ...prev };
          toFetch.forEach((id, i) => {
            next[id] = results[i];
            loadedRef.current.add(id);
          });
          return next;
        });
      } catch (err) {
        console.error('Failed to load GIS datasets:', err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadLayers();
    return () => {
      cancelled = true;
    };
  }, [visibleLayerIds]);

  return { datasets, loading };
}

