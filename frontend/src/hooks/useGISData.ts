import { useState, useEffect } from 'react';

const API_BASE = '/api/v1/layers';

export function useGISData() {
  const [datasets, setDatasets] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    async function loadLayers() {
      try {
        const [autoPlantsRes, powerGridRes, powerPlantsRes, industrialConvergenceRes] = await Promise.all([
          fetch(`${API_BASE}/auto-plants`),
          fetch(`${API_BASE}/power-grid`),
          fetch(`${API_BASE}/power-plants`),
          fetch(`${API_BASE}/industrial-convergence`),
        ]);

        const autoPlants = await autoPlantsRes.json();
        const powerGrid = await powerGridRes.json();
        const powerPlants = await powerPlantsRes.json();
        const industrialConvergence = await industrialConvergenceRes.json();

        setDatasets({
          'auto-plants': autoPlants,
          'power-grid': powerGrid,
          'power-plants': powerPlants,
          'industrial-convergence': industrialConvergence,
        });
      } catch (err) {
        console.error('Failed to load GIS datasets:', err);
      } finally {
        setLoading(false);
      }
    }

    loadLayers();
  }, []);

  return { datasets, loading };
}
