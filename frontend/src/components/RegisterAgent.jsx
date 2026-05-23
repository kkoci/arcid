import React, { useState } from "react";

export default function RegisterAgent({ onRegister }) {
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const data = await onRegister({ name: name.trim() || "Untitled Agent" });
      setResult(data);
      setName("");
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="rounded-lg border border-arc-panel bg-arc-panel/60 backdrop-blur p-4 flex flex-col gap-3">
      <h2 className="text-xl font-semibold">Register Your Agent</h2>
      <p className="text-sm text-arc-dim">
        Generates a synthetic DCAP attestation quote (prototype mode), submits to the ArcID Registry on local Hardhat node, provisions a mock Circle wallet, and binds it on-chain.
      </p>
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Agent display name"
          maxLength={64}
          className="flex-1 bg-arc-bg border border-arc-panel rounded-md px-3 py-2 text-sm focus:outline-none focus:border-arc-accent/60"
          disabled={submitting}
        />
        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-arc-accent text-arc-bg font-medium px-4 py-2 text-sm hover:bg-arc-accent/90 transition disabled:opacity-50"
        >
          {submitting ? "Attesting…" : "Register"}
        </button>
      </form>

      {error && (
        <div className="rounded-md border border-arc-danger/40 bg-arc-danger/10 px-3 py-2 text-sm text-arc-danger">
          {error}
        </div>
      )}

      {result && (
        <div className="rounded-md border border-arc-accent/40 bg-arc-accent/5 px-3 py-3 text-xs font-mono text-arc-ink break-all">
          <div className="text-arc-accent text-sm mb-1">✓ Registered</div>
          <div><span className="text-arc-dim">agent_id:</span> {result.agent_id}</div>
          <div><span className="text-arc-dim">wallet:</span> {result.wallet_address}</div>
          <div><span className="text-arc-dim">tx_hash:</span> {result.tx_hash}</div>
          <div>
            <span className="text-arc-dim">gas:</span>{" "}
            {result.gas_sponsored ? "sponsored by Paymaster" : "paid in USDC"}
          </div>
        </div>
      )}
    </section>
  );
}
