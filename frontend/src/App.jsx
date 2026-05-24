import React, { useState } from "react";
import Leaderboard from "./components/Leaderboard.jsx";
import RegisterAgent from "./components/RegisterAgent.jsx";
import OrderDialog from "./components/OrderDialog.jsx";
import { useArcID } from "./hooks/useArcID.js";

export default function App() {
  const { agents, config, loading, error, registerAgent, placeOrder } = useArcID();
  const [activeAgent, setActiveAgent] = useState(null);

  return (
    <main className="min-h-full max-w-6xl mx-auto px-4 py-10 flex flex-col gap-10">
      <Header config={config} />

      <div className="grid lg:grid-cols-[1fr,1.2fr] gap-6 items-start">
        <RegisterAgent onRegister={registerAgent} prototypeMode={config?.modes?.prototype_mode ?? true} />
        <Leaderboard
          agents={agents}
          loading={loading}
          error={error}
          onOrder={setActiveAgent}
        />
      </div>

      <Footer config={config} />

      <OrderDialog
        agent={activeAgent}
        onClose={() => setActiveAgent(null)}
        onPlace={placeOrder}
      />
    </main>
  );
}

function Header({ config }) {
  return (
    <header className="flex flex-col gap-2">
      <div className="flex items-center gap-3">
        <span className="text-2xl font-semibold tracking-tight">
          Arc<span className="text-arc-accent">ID</span>
        </span>
        <span className="text-xs uppercase tracking-widest text-arc-dim">
          The Verifiable Agent Layer for Arc
        </span>
      </div>
      <p className="text-sm text-arc-dim max-w-2xl">
        A universal identity registry for AI agents. Submit a hardware-signed Intel
        TDX attestation, receive a canonical <code className="font-mono">bytes32</code> agentId
        anchored on Arc, and start earning attributed builder fees on Polymarket V2.
      </p>
      {config && (
        <div className="flex gap-3 text-xs text-arc-dim font-mono pt-1 flex-wrap">
          <span>chain: {config.arc_chain_id}</span>
          <span>registry: {short(config.addresses.ArcIDRegistry)}</span>
          <span>{config.modes.prototype_mode ? "prototype mode" : "live mode"}</span>
        </div>
      )}
    </header>
  );
}

function Footer({ config }) {
  return (
    <footer className="text-xs text-arc-dim flex flex-col gap-1 pt-6 border-t border-arc-panel/60">
      <div>
        ArcID prototype — Canteen x Circle Arc hackathon, May 11–25 2026.
      </div>
      {config && (
        <div className="font-mono">
          USDC: {short(config.addresses.USDC)} · DCAPVerifier: {short(config.addresses.DCAPVerifier)} · Builder: {short(config.addresses.PolymarketBuilder)}
        </div>
      )}
    </footer>
  );
}

function short(hex) {
  if (!hex) return "—";
  return `${hex.slice(0, 6)}…${hex.slice(-4)}`;
}
