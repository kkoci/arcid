import React from "react";

function short(hex, n = 6) {
  if (!hex) return "—";
  return `${hex.slice(0, 2 + n)}…${hex.slice(-n)}`;
}

function formatUsdc(amount) {
  if (!Number.isFinite(amount)) return "0.0000";
  return amount.toFixed(4);
}

/**
 * @param {{ agent: any, rank: number, onOrder: (a: any) => void }} props
 */
export default function AgentCard({ agent, rank, onOrder }) {
  const registered = new Date(agent.registered_at * 1000);
  const fees = agent.builder_fees_usdc ?? 0;
  return (
    <div className="rounded-lg border border-arc-panel bg-arc-panel/60 backdrop-blur p-4 flex flex-col gap-3">
      <div className="flex justify-between items-start">
        <div className="flex items-center gap-3">
          <span className="text-arc-dim text-sm font-mono">#{rank.toString().padStart(2, "0")}</span>
          <div>
            <div className="text-lg font-semibold">{agent.name || "(unnamed)"}</div>
            <div className="text-xs text-arc-dim font-mono break-all">{agent.agent_id}</div>
          </div>
        </div>
        <TeeBadge mrtd={agent.mrtd} />
      </div>

      <div className="grid grid-cols-2 gap-3 text-sm">
        <Stat label="Signer" value={short(agent.attested_signer, 5)} mono />
        <Stat label="Wallet"  value={short(agent.wallet, 5)} mono />
        <Stat label="USDC fees earned" value={formatUsdc(fees)} accent />
        <Stat label="Gas" value={agent.gas_sponsored ? "Sponsored" : "Paid"} />
      </div>

      <div className="flex items-center justify-between mt-1">
        <span className="text-xs text-arc-dim">
          registered {registered.toLocaleString()}
        </span>
        <button
          className="text-sm rounded-md border border-arc-accent/40 px-3 py-1 text-arc-accent hover:bg-arc-accent/10 transition"
          onClick={() => onOrder(agent)}
        >
          Place demo order
        </button>
      </div>
    </div>
  );
}

function Stat({ label, value, mono, accent }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wider text-arc-dim">{label}</div>
      <div className={`${mono ? "font-mono" : ""} ${accent ? "text-arc-accent" : ""}`}>{value}</div>
    </div>
  );
}

function TeeBadge({ mrtd }) {
  return (
    <div
      className="flex items-center gap-2 rounded-full border border-arc-accent/40 bg-arc-accent/10 px-3 py-1 text-arc-accent text-xs"
      title={`MRTD: ${mrtd}`}
    >
      <span className="inline-block w-2 h-2 rounded-full bg-arc-accent animate-pulse" />
      TEE Verified
    </div>
  );
}
