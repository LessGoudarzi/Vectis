import React, { useCallback, useEffect, useRef, useState } from 'react';
import { RotateCw, Server } from 'lucide-react';

// Persisted client-side so the button doesn't demand the token on every
// page load — this is a convenience store, not a security boundary; the
// boundary is the backend's ADMIN_RESTART_TOKEN check.
const TOKEN_STORAGE_KEY = 'vectis_admin_restart_token';

type BackendState = 'idle' | 'needs-token' | 'restarting' | 'waiting' | 'error';

// Polls /health after a restart is triggered so the UI can tell the user
// once the backend is actually back, instead of just firing the request
// and hoping — the backend process is briefly completely gone mid-restart.
async function waitForBackendHealthy(timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      // Under /api/v1 (not plain /health) so this reaches the backend
      // through both the Vite dev proxy and the prod nginx proxy, which
      // only forward the /api prefix.
      const res = await fetch('/api/v1/health');
      if (res.ok) return true;
    } catch {
      // Expected while the process is down/rebinding; keep polling.
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  return false;
}

export const AdminControls: React.FC = () => {
  const [backendState, setBackendState] = useState<BackendState>('idle');
  const [tokenInput, setTokenInput] = useState('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const cancelledRef = useRef(false);

  useEffect(() => () => {
    cancelledRef.current = true;
  }, []);

  const handleRestartFrontend = useCallback(() => {
    window.location.reload();
  }, []);

  const triggerRestart = useCallback(async (token: string) => {
    setBackendState('restarting');
    setErrorMessage(null);
    try {
      const res = await fetch('/api/v1/admin/restart-backend', {
        method: 'POST',
        headers: { 'X-Admin-Token': token },
      });
      if (res.status === 401) {
        localStorage.removeItem(TOKEN_STORAGE_KEY);
        setErrorMessage('Invalid admin token.');
        setBackendState('needs-token');
        return;
      }
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setErrorMessage(body?.detail ?? `Restart failed (${res.status}).`);
        setBackendState('error');
        return;
      }
      localStorage.setItem(TOKEN_STORAGE_KEY, token);
      setBackendState('waiting');
      // Re-ingesting the full power-grid/plants/substations dataset on
      // startup genuinely takes ~2 minutes, not a quick reboot.
      const healthy = await waitForBackendHealthy(3 * 60_000);
      if (cancelledRef.current) return;
      if (healthy) {
        window.location.reload();
      } else {
        setErrorMessage('Backend did not come back within 3 minutes.');
        setBackendState('error');
      }
    } catch {
      setErrorMessage('Could not reach the backend to request a restart.');
      setBackendState('error');
    }
  }, []);

  const handleRestartBackend = useCallback(() => {
    const storedToken = localStorage.getItem(TOKEN_STORAGE_KEY);
    if (storedToken) {
      triggerRestart(storedToken);
    } else {
      setErrorMessage(null);
      setBackendState('needs-token');
    }
  }, [triggerRestart]);

  const handleTokenSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (!tokenInput.trim()) return;
      triggerRestart(tokenInput.trim());
      setTokenInput('');
    },
    [tokenInput, triggerRestart]
  );

  const busy = backendState === 'restarting' || backendState === 'waiting';

  return (
    <div className="absolute bottom-4 left-4 z-30 flex flex-col gap-1.5 rounded-lg border border-slate-700 bg-slate-900/95 p-2.5 text-xs text-white shadow-xl backdrop-blur-md">
      <div className="flex gap-1.5">
        <button
          onClick={handleRestartFrontend}
          className="flex items-center gap-1.5 rounded bg-cyan-500/15 px-2 py-1.5 font-medium text-cyan-300 hover:bg-cyan-500/25"
          title="Reload this page"
        >
          <RotateCw className="h-3 w-3" />
          Restart Frontend
        </button>
        <button
          onClick={handleRestartBackend}
          disabled={busy}
          className="flex items-center gap-1.5 rounded bg-cyan-500/15 px-2 py-1.5 font-medium text-cyan-300 hover:bg-cyan-500/25 disabled:cursor-not-allowed disabled:opacity-50"
          title="Restart the FastAPI backend process"
        >
          <Server className="h-3 w-3" />
          {backendState === 'restarting' && 'Restarting…'}
          {backendState === 'waiting' && 'Waiting for backend…'}
          {backendState !== 'restarting' && backendState !== 'waiting' && 'Restart Backend'}
        </button>
      </div>

      {backendState === 'needs-token' && (
        <form onSubmit={handleTokenSubmit} className="flex gap-1.5">
          <input
            type="password"
            autoFocus
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            placeholder="Admin restart token"
            className="min-w-0 flex-1 rounded border border-slate-600 bg-slate-800 px-2 py-1 text-[11px] text-white placeholder:text-slate-500"
          />
          <button
            type="submit"
            className="shrink-0 rounded bg-cyan-500/15 px-2 py-1 text-[11px] font-medium text-cyan-300 hover:bg-cyan-500/25"
          >
            Go
          </button>
        </form>
      )}

      {errorMessage && <span className="text-[11px] text-red-400">{errorMessage}</span>}
    </div>
  );
};
