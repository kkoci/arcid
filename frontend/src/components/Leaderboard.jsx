import React, { useMemo } from "react";
import AgentCard from "./AgentCard.jsx";

export default function Leaderboard({ agents, onOrder, loading, error }) {
  const ranked = useMemo(() => {
    return [...agents].sort((a, b) => {
      const fa = a.builder_fees_usdc ?? 0;
      const fb = b.builder_fees_usdc ?? 0;
      if (fb !== fa) return fb - fa;
      return (a.registered_at ?? 0) - (b.registered_at ?? 0);
    });
  }, [agents]);

  return (
    <section className="flex flex-col gap-3">
      <header className="flex items-baseline justify-between">
        <h2 className="text-xl font-semibold">Verified Agents</h2>
        <span className="text-sm text-arc-dim">
          {loading ? "syncing…" : `${ranked.length} registered`}
        </span>
      </header>

      {error && (
        <div className="rounded-md border border-arc-danger/40 bg-arc-danger/10 px-4 py-3 text-sm text-arc-danger">
          {error}
        </div>
      )}

      {ranked.length === 0 && !loading && !error && (
        <div className="rounded-md border border-arc-panel bg-arc-panel/40 px-4 py-6 text-center text-sm text-arc-dim">
          No agents registered yet. Register the first one →
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {ranked.map((a, i) => (
          <AgentCard key={a.agent_id} agent={a} rank={i + 1} onOrder={onOrder} />
        ))}
      </div>
    </section>
  );
}
