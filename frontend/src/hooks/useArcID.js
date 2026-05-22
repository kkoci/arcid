import { useCallback, useEffect, useState } from "react";

// In dev, Vite proxies /api → http://localhost:8000.
// In production, set VITE_API_BASE_URL to the full backend URL (no trailing slash).
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

async function jsonOrThrow(res) {
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${text ? `: ${text}` : ""}`);
  }
  return res.json();
}

/** Single source of truth for ArcID API interaction. */
export function useArcID() {
  const [agents, setAgents] = useState([]);
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cfg, list] = await Promise.all([
        fetch(`${API_BASE}/config`).then(jsonOrThrow),
        fetch(`${API_BASE}/agents?offset=0&limit=100`).then(jsonOrThrow),
      ]);
      setConfig(cfg);
      setAgents(list.agents || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 8000);
    return () => clearInterval(t);
  }, [refresh]);

  const registerAgent = useCallback(async ({ name }) => {
    const res = await fetch(`${API_BASE}/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const data = await jsonOrThrow(res);
    await refresh();
    return data;
  }, [refresh]);

  const placeOrder = useCallback(async (agentId, { market_question, side, size_usdc }) => {
    const res = await fetch(`${API_BASE}/agents/${agentId}/order`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ market_question, side, size_usdc }),
    });
    return jsonOrThrow(res);
  }, []);

  return { agents, config, loading, error, refresh, registerAgent, placeOrder };
}
