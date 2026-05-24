import { useState, useEffect } from 'react'
import WalletConnect from './WalletConnect'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

async function apiGet(path) {
  try {
    const res = await fetch(`${API_BASE}${path}`)
    if (!res.ok) return null
    return res.json()
  } catch { return null }
}

export default function Landing({ onNavigate, onConnect, onDisconnect, walletAddr }) {
  const [stats, setStats]           = useState(null)
  const [agentStatus, setAgentStatus] = useState(null)
  const [regime, setRegime]         = useState(null)

  useEffect(() => {
    async function load() {
      const [contracts, agent, reg, strategies] = await Promise.all([
        apiGet('/api/config/contracts'),
        apiGet('/api/agent/status'),
        apiGet('/api/regime/current'),
        apiGet('/api/strategies/'),
      ])
      setStats({
        strategyCount: strategies?.strategies?.length || 0,
        contracts: contracts?.vault_factory ? 10 : 0,
      })
      setAgentStatus(agent)
      setRegime(reg)
    }
    load()
  }, [])

  return (
    <div className="min-h-screen bg-[var(--canvas)] overflow-x-hidden font-[var(--sans)]">

      {/* ── Fixed minimal header ─────────────────────────────────── */}
      <header className="fixed top-0 inset-x-0 z-50 flex items-center justify-between px-5 md:px-8 h-14 bg-[rgba(9,9,11,0.88)] backdrop-blur-[16px] border-b border-[var(--glass-border)]">
        <div className="flex items-center gap-2.5">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" className="w-7 h-7 flex-shrink-0" aria-hidden="true">
            <rect width="32" height="32" rx="4" fill="#0a0a0b"/>
            <text x="16" y="23" textAnchor="middle" fontFamily="serif" fontSize="22" fill="#e0a64f">Λ</text>
          </svg>
          <span className="font-bold text-[1rem] tracking-tight text-[var(--text-1)]">Archimedes</span>
        </div>
        <div className="flex items-center gap-3">
          <button
            className="btn-secondary !py-2 !px-4 !text-sm"
            onClick={() => onNavigate('library')}
          >
            Strategies
          </button>
          {walletAddr ? (
            <button className="btn-primary !py-2 !px-4 !text-sm" onClick={() => onNavigate('portfolio')}>
              Dashboard →
            </button>
          ) : (
            <WalletConnect address={walletAddr} onConnect={onConnect} onDisconnect={onDisconnect} />
          )}
        </div>
      </header>

      {/* ── Hero ─────────────────────────────────────────────────── */}
      <section className="pt-28 pb-16 px-4 text-center border-b border-[var(--glass-border)] bg-[var(--canvas)] sm:px-6 sm:pt-32 sm:pb-20 lg:px-12 lg:pt-40 lg:pb-28">
        <div className="max-w-[760px] mx-auto">
          <span style={{
            display: 'inline-block',
            fontSize: '0.7rem',
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.12em',
            color: 'var(--accent)',
            border: '1px solid var(--accent)',
            borderRadius: '9999px',
            padding: '4px 16px',
            marginBottom: '28px',
            opacity: 0.85,
          }}>
            Agora Agents Hackathon 2026
          </span>
          <p className="font-serif italic text-[1rem] text-[var(--text-3)] mb-4 md:text-[1.1rem]">
            Linus for quantitative finance.
          </p>
          <h1 className="font-serif text-[2.1rem] font-normal leading-[1.1] mb-6 text-[var(--text-1)] sm:text-[2.8rem] lg:text-[3.4rem]">
            <span className="text-[var(--accent)]">Paper-Grounded.</span><br />
            On-Chain Verifiable.<br />
            <span className="text-[var(--text-3)]">Autonomously Managed.</span>
          </h1>
          <p className="text-[0.98rem] leading-[1.75] text-[var(--text-2)] max-w-[620px] mx-auto mb-10 md:text-[1.08rem]">
            Archimedes turns peer-reviewed quant research into rigor-gated, investable
            strategies — generated for your brief, executed in non-custodial vaults
            on Arc, with every decision hashed and verifiable on-chain.
          </p>
          <div className="flex flex-col items-stretch gap-3 sm:flex-row sm:justify-center sm:items-center">
            <button className="btn-primary" onClick={() => onNavigate('generate')}>
              Generate a Strategy →
            </button>
            <button className="btn-secondary" onClick={() => onNavigate('library')}>
              Browse Example Library
            </button>
          </div>
          <p className="caption mt-5 text-[var(--text-4)]">
            No wallet needed to generate. Wallet only required to deposit into a vault.
          </p>
        </div>
      </section>

      {/* ── Live status bar ──────────────────────────────────────── */}
      <div className="flex flex-wrap justify-center gap-x-8 gap-y-2 px-5 py-3.5 overflow-hidden bg-[var(--surface-1)] border-b border-[var(--glass-border)]">
        <StatusItem dot="live"   label="Agent"      value={agentStatus?.alive ? 'LIVE' : '…'} />
        <StatusItem dot="regime" label="Regime"     value={regime?.regime || '…'} />
        <StatusItem              label="Confidence" value={regime?.confidence ? `${(regime.confidence * 100).toFixed(0)}%` : '…'} />
        <StatusItem              label="Strategies" value={stats?.strategyCount ?? '…'} />
        <StatusItem              label="Contracts"  value={stats?.contracts ?? '…'} />
      </div>

      {/* ── Why Archimedes ───────────────────────────────────────── */}
      <LSection>
        <SectionTitle>Why Archimedes?</SectionTitle>
        <div className="lg-grid-4">
          <FeatureCard icon="file-text" title="Paper-Grounded Strategies" tag="SMA200 · TSMOM · Vol-Managed">
            Every strategy is extracted from published, peer-reviewed quant finance
            research. No vibes, no hype — academic rigor meets autonomous execution.
          </FeatureCard>
          <FeatureCard icon="link" title="On-Chain Provenance" tag="Commit-Reveal · Verifiable">
            Every rebalance decision gets a keccak256 hash anchored on Arc.
            Verify the agent's reasoning trail — before and after each trade.
          </FeatureCard>
          <FeatureCard icon="bot" title="Autonomous Agent" tag="Live · 5-min ticks">
            The agent evaluates 4 paper-grounded strategies against live market data,
            detects regime shifts, and rebalances autonomously — USDC on Arc.
          </FeatureCard>
          <FeatureCard icon="lock" title="Non-Custodial Vaults" tag="ERC-4626 · Your Keys">
            Your funds never pass through platform custody. ERC-4626 vault contracts
            hold your USDC and synth tokens — agent has rebalance authority only.
          </FeatureCard>
        </div>
      </LSection>

      {/* ── Two-Tier Marketplace ─────────────────────────────────── */}
      <LSection>
        <SectionTitle>Two-Tier Strategy Marketplace</SectionTitle>
        <div className="lg-grid-2">
          <TierCard tier={1} title="Archimedes Verified" items={[
            'Paper-grounded provenance',
            'Selection-bias corrected (DSR + PBO + walk-forward + look-ahead audit)',
            'Full agent autonomy',
            'Reasoning trace on-chain',
            'Paper-claim deltas surfaced honestly',
          ]} />
          <TierCard tier={2} title="Community" items={[
            'Permissionless strategy submission',
            'Opt-in agent features',
            'Community curation',
            'Transparent performance history',
            'Open to all strategies',
          ]} />
        </div>
        <div className="mt-4 text-center">
          <button className="btn-secondary" onClick={() => onNavigate('library')}>
            Browse {stats?.strategyCount || 6} Strategies →
          </button>
        </div>
      </LSection>

      {/* ── Built On ─────────────────────────────────────────────── */}
      <LSection>
        <SectionTitle>Built On</SectionTitle>
        <div className="flex gap-3 overflow-x-auto pb-1 justify-center flex-wrap lg:flex-nowrap max-w-full mx-auto">
          {[
            { name: 'Arc',         desc: 'EVM · Sub-second finality' },
            { name: 'Circle',      desc: 'USDC · Wallets · CCTP' },
            { name: 'Foundry',     desc: '10 deployed contracts' },
            { name: 'Claude',      desc: 'Strategy extraction · Reasoning' },
            { name: 'React + viem',desc: 'Frontend · Wallet UX' },
            { name: 'FastAPI',     desc: 'Backend · Agent runner' },
          ].map(t => (
            <div key={t.name} className="flex flex-col items-center px-5 py-3 min-w-[140px] flex-shrink-0 bg-[var(--surface-2)] border border-[var(--glass-border)] rounded-lg">
              <span className="text-sm font-semibold text-[var(--text-1)]">{t.name}</span>
              <span className="text-xs text-[var(--text-3)] mt-0.5">{t.desc}</span>
            </div>
          ))}
        </div>
      </LSection>

      {/* ── Rigor ────────────────────────────────────────────────── */}
      <LSection>
        <SectionTitle>Rigor is the Wedge</SectionTitle>
        <p className="text-sm text-center text-[var(--text-2)] mb-8 max-w-lg mx-auto">
          Every Tier 1 strategy passes four selection-bias correction gates before admission:
        </p>
        <div className="lg-grid-4">
          {[
            { n: '01', title: 'Deflated Sharpe Ratio',              desc: 'Bailey & López de Prado 2014 — corrects for multiple-testing inflation' },
            { n: '02', title: 'Probability of Backtest Overfitting', desc: 'Bailey/Borwein/López de Prado/Zhu 2014 — detects curve-fitting' },
            { n: '03', title: 'Walk-Forward OOS Sharpe',             desc: 'Rolling window validation with no in/out-of-sample cliff' },
            { n: '04', title: 'Look-Ahead Audit',                    desc: 'Static lint for future-leaking function calls in strategy code' },
          ].map(r => (
            <div key={r.n} className="bg-[var(--surface-1)] border border-[var(--glass-border)] rounded-xl p-6">
              <div className="font-mono text-[2.5rem] font-bold text-[var(--accent)] opacity-30 leading-none mb-2">{r.n}</div>
              <h4 className="text-sm font-semibold text-[var(--text-1)] mb-1.5">{r.title}</h4>
              <p className="text-xs text-[var(--text-3)] leading-relaxed">{r.desc}</p>
            </div>
          ))}
        </div>
      </LSection>

      {/* ── Circle Ecosystem ─────────────────────────────────────── */}
      <LSection>
        <SectionTitle>Circle Ecosystem Integration</SectionTitle>
        <div className="lg-grid-3">
          <FeatureCard icon="wallet"            title="Developer-Controlled Wallets" tag="Agent Signing · RSA-OAEP">
            Agent executes on-chain transactions (rebalances, trace publishing)
            via Circle-managed developer wallet with entity secret encryption.
          </FeatureCard>
          <FeatureCard icon="circle-dollar-sign" title="USDC Settlement"             tag="Native USDC · 6 decimals">
            All vault deposits, trades, and redemptions settle in USDC on Arc.
            Native USDC at 0x3600…0000 on Arc testnet.
          </FeatureCard>
          <FeatureCard icon="scroll-text"       title="Smart Contracts on Arc"       tag="10 Contracts · Foundry">
            10 Solidity contracts deployed: Vault, VaultFactory, AMMPool,
            AMMRouter, SyntheticFactory, PriceOracle, ReasoningTraceRegistry.
          </FeatureCard>
          <FeatureCard icon="arrow-left-right"  title="CCTP Cross-Chain"             tag="Bridge · Arbitrum · ETH">
            Bridge USDC across chains via Circle's CCTP protocol.
            Arc testnet supports CCTP for seamless cross-chain liquidity.
          </FeatureCard>
          <FeatureCard icon="zap"               title="Paymaster (Gasless)"           tag="Sponsor · ERC-4337">
            Arc Paymaster enables gasless transactions for users.
            Users can interact with vaults without holding native gas tokens.
          </FeatureCard>
          <FeatureCard icon="layers"            title="Gateway + USYC"               tag="Nanopayments · Balance API">
            Unified balance queries across chains. USYC yield token integration
            for vault floor enforcement per risk profile.
          </FeatureCard>
        </div>
      </LSection>

      {/* ── CTA ──────────────────────────────────────────────────── */}
      <section className="py-16 px-4 text-center border-b border-[var(--glass-border)] sm:px-6 lg:py-20 lg:px-12">
        <h2 className="font-serif text-[1.8rem] font-normal text-[var(--text-1)] mb-3 md:text-[2.2rem]">
          Give me a lever long enough<br />and I shall move the world.
        </h2>
        <p className="text-xs font-semibold uppercase tracking-[0.08em] text-[var(--text-3)] mb-6">
          — Archimedes (paraphrased)
        </p>
        <p className="text-sm text-[var(--text-2)] leading-relaxed mb-8">
          The lever is academic research.<br />
          The fulcrum is autonomous AI.<br />
          The world is your portfolio.
        </p>
        <div className="hero-actions flex justify-center items-center gap-3">
          {walletAddr ? (
            <button className="btn-primary" onClick={() => onNavigate('portfolio')}>
              Open Portfolio →
            </button>
          ) : (
            <WalletConnect address={walletAddr} onConnect={onConnect} onDisconnect={onDisconnect} />
          )}
          <button className="btn-secondary" onClick={() => onNavigate('generate')}>
            Generate a Strategy →
          </button>
        </div>
        <p className="mt-8 text-xs text-[var(--text-4)]">
          Powered by{' '}
          <strong className="text-[var(--text-2)]">Arc</strong>
          {' × '}
          <strong className="text-[var(--text-2)]">Circle</strong>
          {' × '}
          <strong className="text-[var(--text-2)]">Canteen</strong>
        </p>
      </section>

    </div>
  )
}

/* ── Sub-components ──────────────────────────────────────────── */

function StatusItem({ dot, label, value }) {
  const dotCls =
    dot === 'live'   ? 'bg-[var(--positive)] shadow-[0_0_6px_var(--positive)]' :
    dot === 'regime' ? 'bg-[var(--accent)]' : null
  return (
    <div className="flex items-center gap-1.5 text-[0.82rem]">
      {dotCls && (
        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dotCls}`} />
      )}
      <span className="text-[var(--text-3)]">{label}</span>
      <span className="text-[var(--text-1)] font-semibold tabular-nums">{value}</span>
    </div>
  )
}

function LSection({ children }) {
  return (
    <section className="l-section">
      {children}
    </section>
  )
}

function SectionTitle({ children }) {
  return (
    <h2 style={{fontFamily:'var(--serif)',fontSize:'1.6rem',fontWeight:400,textAlign:'center',marginBottom:'2rem',color:'var(--text-1)',width:'100%'}}>
      {children}
    </h2>
  )
}

function FeatureCard({ icon, title, tag, children }) {
  return (
    <div className="flex flex-col bg-[var(--surface-1)] border border-[var(--glass-border)] rounded-xl p-6 hover:border-[var(--accent)] transition-colors duration-200">
      <span className={`i-lucide-${icon} w-7 h-7 mb-3`} style={{color: '#D4A853'}} />
      <h3 className="text-[1rem] font-semibold mb-2 text-[var(--text-1)]">{title}</h3>
      <p className="text-[0.85rem] leading-[1.6] text-[var(--text-2)] mb-3 flex-1">{children}</p>
      <span className="inline-block self-start text-[0.7rem] font-semibold px-2.5 py-1 rounded" style={{color: '#D4A853', background: 'rgba(212,168,83,0.08)'}}>
        {tag}
      </span>
    </div>
  )
}

function TierCard({ tier, title, items }) {
  const borderCls = tier === 1 ? 'border-[var(--accent)]' : 'border-[var(--text-3)]'
  const colorCls  = tier === 1 ? 'text-[var(--accent)]'   : 'text-[var(--text-3)]'
  const iconName  = tier === 1 ? 'i-lucide-trophy'        : 'i-lucide-users'
  return (
    <div className={`bg-[var(--surface-1)] border-2 ${borderCls} rounded-2xl p-8 flex flex-col items-center text-center`}>
      <span className={`${iconName} w-8 h-8 mb-3 ${colorCls}`} />
      <div className={`text-xs font-bold uppercase tracking-[0.08em] ${colorCls} mb-2`}>
        Tier {tier}
      </div>
      <h3 className="font-serif text-[1.15rem] font-normal mb-5 text-[var(--text-1)]">{title}</h3>
      <ul className="space-y-2 text-left w-full">
        {items.map(item => (
          <li key={item} className="flex items-start gap-2 text-[0.85rem] text-[var(--text-2)]">
            <span className="i-lucide-check w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-[var(--positive)]" />
            {item}
          </li>
        ))}
      </ul>
    </div>
  )
}
