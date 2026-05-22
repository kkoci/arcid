import React, { useState } from "react";

const DEFAULT_MARKET = "Will Agora have >200 submissions?";

export default function OrderDialog({ agent, onClose, onPlace }) {
  const [side, setSide] = useState("YES");
  const [size, setSize] = useState(1.0);
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  if (!agent) return null;

  async function submit() {
    setPending(true);
    setError(null);
    try {
      const r = await onPlace(agent.agent_id, {
        market_question: DEFAULT_MARKET,
        side,
        size_usdc: Number(size),
      });
      setResult(r);
    } catch (e) {
      setError(e.message);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="fixed inset-0 z-10 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-full max-w-md rounded-lg border border-arc-panel bg-arc-bg p-5 flex flex-col gap-3"
        onClick={(e) => e.stopPropagation()}
      >
        <header>
          <h3 className="text-lg font-semibold">Attributed order</h3>
          <p className="text-xs text-arc-dim font-mono break-all">{agent.agent_id}</p>
        </header>

        <div className="text-sm text-arc-ink">
          Market:
          <div className="mt-1 font-medium">{DEFAULT_MARKET}</div>
        </div>

        <div className="flex gap-2">
          {["YES", "NO"].map((s) => (
            <button
              key={s}
              onClick={() => setSide(s)}
              className={`flex-1 rounded-md py-2 text-sm border transition ${
                side === s
                  ? "bg-arc-accent text-arc-bg border-arc-accent"
                  : "border-arc-panel text-arc-ink hover:border-arc-accent/40"
              }`}
            >
              {s}
            </button>
          ))}
        </div>

        <label className="flex flex-col gap-1 text-sm">
          <span className="text-arc-dim text-xs uppercase tracking-wider">Size (USDC)</span>
          <input
            type="number"
            min="0.10"
            max="100"
            step="0.10"
            value={size}
            onChange={(e) => setSize(e.target.value)}
            className="bg-arc-panel border border-arc-panel rounded-md px-3 py-2 focus:outline-none focus:border-arc-accent/60"
          />
        </label>

        {error && (
          <div className="rounded-md border border-arc-danger/40 bg-arc-danger/10 px-3 py-2 text-sm text-arc-danger">
            {error}
          </div>
        )}

        {result && (
          <div className="rounded-md border border-arc-accent/40 bg-arc-accent/5 px-3 py-3 text-xs font-mono break-all">
            <div className="text-arc-accent text-sm mb-1">✓ Filled</div>
            <div><span className="text-arc-dim">venue:</span> {result.venue}</div>
            <div><span className="text-arc-dim">fee:</span> {result.builder_fee_usdc} USDC</div>
            {result.tx_hash && <div><span className="text-arc-dim">tx:</span> {result.tx_hash}</div>}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <button
            className="text-sm rounded-md border border-arc-panel px-3 py-1 text-arc-dim hover:text-arc-ink"
            onClick={onClose}
          >
            Close
          </button>
          <button
            disabled={pending}
            className="text-sm rounded-md bg-arc-accent text-arc-bg font-medium px-3 py-1 disabled:opacity-50"
            onClick={submit}
          >
            {pending ? "Submitting…" : "Place order"}
          </button>
        </div>
      </div>
    </div>
  );
}
