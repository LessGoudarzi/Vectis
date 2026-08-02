import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fetchTrace, TraceableLayerId, TraceResult } from '../networkTrace';

const INITIAL_MAX_MILES = 250;
const TRACE_FURTHER_STEP_MILES = 250;
const REVEAL_MILES_PER_SECOND = 60;

export function useNetworkTrace() {
  const [sourceLayerId, setSourceLayerId] = useState<TraceableLayerId | null>(null);
  const [plantId, setPlantId] = useState<number | null>(null);
  const [plantName, setPlantName] = useState<string | null>(null);
  const [maxMiles, setMaxMiles] = useState(INITIAL_MAX_MILES);
  const [allowCrossSubregion, setAllowCrossSubregion] = useState(false);
  const [result, setResult] = useState<TraceResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [revealedMiles, setRevealedMiles] = useState(0);
  const [playing, setPlaying] = useState(true);

  const rafRef = useRef<number | null>(null);
  const lastTsRef = useRef<number | null>(null);

  const maxDistance = useMemo(() => {
    const lines = result?.lines ?? [];
    return lines.reduce((max, l) => Math.max(max, l.distance_from_origin_miles), 0);
  }, [result]);

  const revealedLineIds = useMemo(() => {
    const lines = result?.lines ?? [];
    return new Set(lines.filter((l) => l.distance_from_origin_miles <= revealedMiles).map((l) => l.line_id));
  }, [result, revealedMiles]);

  const runFetch = useCallback(
    async (layerId: TraceableLayerId, id: number, name: string, requestedMaxMiles: number, requestedCrossSubregion: boolean) => {
      setLoading(true);
      setSourceLayerId(layerId);
      setPlantId(id);
      setPlantName(name);
      setMaxMiles(requestedMaxMiles);
      setAllowCrossSubregion(requestedCrossSubregion);
      try {
        const data = await fetchTrace(layerId, id, requestedMaxMiles, requestedCrossSubregion);
        setResult(data);
        setRevealedMiles(0);
        setPlaying(data.status === 'ok');
      } catch (err) {
        console.error('Network trace failed:', err);
        setResult({ status: 'unavailable' });
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const startTrace = useCallback(
    (layerId: TraceableLayerId, id: number, name: string) => runFetch(layerId, id, name, INITIAL_MAX_MILES, false),
    [runFetch]
  );

  // Extending mileage alone can't cross a subregion boundary — the API
  // enforces that regardless of max_miles — so this behaves differently
  // depending on why the trace stopped last time.
  const traceFurther = useCallback(() => {
    if (sourceLayerId == null || plantId == null || plantName == null) return;
    if (result?.stopped_reason === 'subregion_boundary') {
      runFetch(sourceLayerId, plantId, plantName, maxMiles, true);
    } else {
      runFetch(sourceLayerId, plantId, plantName, maxMiles + TRACE_FURTHER_STEP_MILES, allowCrossSubregion);
    }
  }, [sourceLayerId, plantId, plantName, maxMiles, allowCrossSubregion, result, runFetch]);

  const clearTrace = useCallback(() => {
    setSourceLayerId(null);
    setPlantId(null);
    setPlantName(null);
    setResult(null);
    setRevealedMiles(0);
    setPlaying(false);
  }, []);

  const togglePlay = useCallback(() => setPlaying((p) => !p), []);

  useEffect(() => {
    if (!playing || maxDistance <= 0) return;
    lastTsRef.current = null;

    function tick(ts: number) {
      if (lastTsRef.current == null) lastTsRef.current = ts;
      const dtSeconds = (ts - lastTsRef.current) / 1000;
      lastTsRef.current = ts;
      setRevealedMiles((prev) => {
        const next = prev + dtSeconds * REVEAL_MILES_PER_SECOND;
        if (next >= maxDistance) {
          setPlaying(false);
          return maxDistance;
        }
        return next;
      });
      rafRef.current = requestAnimationFrame(tick);
    }
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, [playing, maxDistance]);

  return {
    sourceLayerId,
    plantId,
    plantName,
    result,
    loading,
    maxMiles,
    revealedMiles,
    maxDistance,
    revealedLineIds,
    playing,
    active: plantId != null,
    startTrace,
    traceFurther,
    clearTrace,
    togglePlay,
  };
}
