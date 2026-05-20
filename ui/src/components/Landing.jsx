import { useState, useEffect } from 'react'
import { publicClient, USDC } from '../config'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

async function apiGet(path) {
  try {
    const res = await fetch(`${API_BASE}${path}`)
    if (!res.ok) return null
    return res.json()
  } catch { return null }
}

export default function Landing({ onNavigate, onConnect, walletAddr }) {
  const [stats, setStats] = useState(null)
  const [agentStatus, setAgentStatus] = useState(null)
  const [regime, setRegime] = useState(null)

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
        synthCount: contracts?.synthetics ? Object.keys(contracts.synthetics).length : 0,
        contracts: contracts?.vault_factory ? 10 : 0,
      })
      setAgentStatus(agent)
      setRegime(reg)
    }
    load()
  }, [])

  return (
    <div className="landing-page">
      {/* ─── Hero Section ─── */}
      <section className="landing-hero">
        <div className="hero-particles" />
        <div className="hero-content">
          <div className="hero-badge">Agora Agents Hackathon 2026</div>
          <h1 className="hero-title">
            <span className="hero-title-accent">Paper-Grounded.</span>
            <br />
            On-Chain Verifiable.
            <br />
            <span className="hero-title-dim">Autonomously Managed.</span>
          </h1>
          <p className="hero-subtitle">
            Archimedes turns published quant research into investable strategies.<br/>
            It constructs personalized portfolios of synthetic RWA tokens on Arc<br/>
            — with every decision hashed and verifiable on-chain.
          </p>
          <div className="hero-actions">
            {walletAddr ? (
              <button className="btn-primary" onClick={() => onNavigate('explore')}>
                Explore Marketplace →
              </button>
            ) : (
              <button className="btn-primary" onClick={onConnect}>
                Connect Wallet to Start
              </button>
            )}
            <button className="btn-secondary" onClick={() => onNavigate('strategies')}>
              View Strategies
            </button>
          </div>
        </div>
      </section>

      {/* ─── Live Status Bar ─── */}
      <section className="landing-status-bar">
        <div className="status-item">
          <span className="status-dot live" />
          <span className="status-label">Agent</span>
          <span className="status-value">{agentStatus?.alive ? 'LIVE' : '...'}</span>
        </div>
        <div className="status-item">
          <span className="status-dot regime" />
          <span className="status-label">Regime</span>
          <span className="status-value">{regime?.regime || '...'}</span>
        </div>
        <div className="status-item">
          <span className="status-label">Confidence</span>
          <span className="status-value">{regime?.confidence ? `${(regime.confidence * 100).toFixed(0)}%` : '...'}</span>
        </div>
        <div className="status-item">
          <span className="status-label">Strategies</span>
          <span className="status-value">{stats?.strategyCount || '...'}</span>
        </div>
        <div className="status-item">
          <span className="status-label">Contracts</span>
          <span className="status-value">{stats?.contracts || '...'}</span>
        </div>
      </section>

      {/* ─── Value Propositions ─── */}
      <section className="landing-features">
        <h2 className="section-title">Why Archimedes?</h2>
        <div className="features-grid">
          <div className="feature-card">
            <div className="feature-icon">📄</div>
            <h3>Paper-Grounded Strategies</h3>
            <p>
              Every strategy is extracted from published, peer-reviewed quant finance
              research. No vibes, no hype — academic rigor meets autonomous execution.
            </p>
            <div className="feature-tag">SMA200 · TSMOM · Vol-Managed</div>
          </div>

          <div className="feature-card">
            <div className="feature-icon">⛓️</div>
            <h3>On-Chain Provenance</h3>
            <p>
              Every rebalance decision gets a keccak256 hash anchored on Arc.
              Verify the agent's reasoning trail — before and after each trade.
            </p>
            <div className="feature-tag">Commit-Reveal · Verifiable</div>
          </div>

          <div className="feature-card">
            <div className="feature-icon">🤖</div>
            <h3>Autonomous Agent</h3>
            <p>
              The agent evaluates 4 paper-grounded strategies against live market data,
              detects regime shifts, and rebalances autonomously — with USDC settlement
              on Arc at sub-second finality.
            </p>
            <div className="feature-tag">Live · 5-min ticks</div>
          </div>

          <div className="feature-card">
            <div className="feature-icon">🔒</div>
            <h3>Non-Custodial Vaults</h3>
            <p>
              Your funds never pass through platform custody. ERC-4626 vault contracts
              hold your USDC and synth tokens — the agent has rebalance authority only.
            </p>
            <div className="feature-tag">ERC-4626 · Your Keys</div>
          </div>
        </div>
      </section>

      {/* ─── Two-Tier Marketplace ─── */}
      <section className="landing-marketplace">
        <h2 className="section-title">Two-Tier Strategy Marketplace</h2>
        <div className="tier-cards">
          <div className="tier-card tier-1">
            <div className="tier-badge">🏆 Tier 1</div>
            <h3>Archimedes Verified</h3>
            <ul>
              <li>Paper-grounded provenance</li>
              <li>Selection-bias corrected (DSR + PBO + walk-forward + look-ahead audit)</li>
              <li>Full agent autonomy</li>
              <li>Reasoning trace on-chain</li>
              <li>Paper-claim deltas surfaced honestly</li>
            </ul>
          </div>
          <div className="tier-card tier-2">
            <div className="tier-badge">👥 Tier 2</div>
            <h3>Community</h3>
            <ul>
              <li>Permissionless strategy submission</li>
              <li>Opt-in agent features</li>
              <li>Community curation</li>
              <li>Transparent performance history</li>
              <li>Open to all strategies</li>
            </ul>
          </div>
        </div>
      </section>

      {/* ─── Tech Stack ─── */}
      <section className="landing-tech">
        <h2 className="section-title">Built On</h2>
        <div className="tech-logos">
          <div className="tech-item">
            <span className="tech-name">Arc</span>
            <span className="tech-desc">EVM · Sub-second finality</span>
          </div>
          <div className="tech-item">
            <span className="tech-name">Circle</span>
            <span className="tech-desc">USDC · Wallets · CCTP</span>
          </div>
          <div className="tech-item">
            <span className="tech-name">Foundry</span>
            <span className="tech-desc">10 deployed contracts</span>
          </div>
          <div className="tech-item">
            <span className="tech-name">Claude</span>
            <span className="tech-desc">Strategy extraction · Reasoning</span>
          </div>
          <div className="tech-item">
            <span className="tech-name">React + viem</span>
            <span className="tech-desc">Frontend · Wallet UX</span>
          </div>
          <div className="tech-item">
            <span className="tech-name">FastAPI</span>
            <span className="tech-desc">Backend · Agent runner</span>
          </div>
        </div>
      </section>

      {/* ─── Selection Bias ─── */}
      <section className="landing-rigor">
        <h2 className="section-title">Rigor is the Wedge</h2>
        <p className="rigor-desc">
          Every Tier 1 strategy passes four selection-bias correction gates before admission:
        </p>
        <div className="rigor-grid">
          <div className="rigor-item">
            <span className="rigor-num">01</span>
            <h4>Deflated Sharpe Ratio</h4>
            <p>Bailey & López de Prado 2014 — corrects for multiple-testing inflation</p>
          </div>
          <div className="rigor-item">
            <span className="rigor-num">02</span>
            <h4>Probability of Backtest Overfitting</h4>
            <p>Bailey/Borwein/López de Prado/Zhu 2014 — detects curve-fitting</p>
          </div>
          <div className="rigor-item">
            <span className="rigor-num">03</span>
            <h4>Walk-Forward OOS Sharpe</h4>
            <p>Rolling window validation with no in/out-of-sample cliff</p>
          </div>
          <div className="rigor-item">
            <span className="rigor-num">04</span>
            <h4>Look-Ahead Audit</h4>
            <p>Static lint for future-leaking function calls in strategy code</p>
          </div>
        </div>
      </section>

      {/* ─── Circle Integration ─── */}
      <section className="landing-tech">
        <h2 className="section-title">Circle Ecosystem Integration</h2>
        <div className="features-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
          <div className="feature-card">
            <div className="feature-icon">💰</div>
            <h3>Developer-Controlled Wallets</h3>
            <p>
              Agent executes on-chain transactions (rebalances, trace publishing)
              via Circle-managed developer wallet with entity secret encryption.
            </p>
            <div className="feature-tag">Agent Signing · RSA-OAEP</div>
          </div>
          <div className="feature-card">
            <div className="feature-icon">🪙</div>
            <h3>USDC Settlement</h3>
            <p>
              All vault deposits, trades, and redemptions settle in USDC on Arc.
              Native USDC at 0x3600...0000 on Arc testnet.
            </p>
            <div className="feature-tag">Native USDC · 6 decimals</div>
          </div>
          <div className="feature-card">
            <div className="feature-icon">📜</div>
            <h3>Smart Contracts on Arc</h3>
            <p>
              10 Solidity contracts deployed: Vault, VaultFactory, AMMPool,
              AMMRouter, SyntheticFactory, PriceOracle, ReasoningTraceRegistry.
            </p>
            <div className="feature-tag">10 Contracts · Foundry</div>
          </div>
          <div className="feature-card">
            <div className="feature-icon">🌉</div>
            <h3>CCTP Cross-Chain</h3>
            <p>
              Bridge USDC across chains via Circle's CCTP protocol.
              Arc testnet supports CCTP for seamless cross-chain liquidity.
            </p>
            <div className="feature-tag">Bridge · Arbitrum · ETH</div>
          </div>
          <div className="feature-card">
            <div className="feature-icon">⛽</div>
            <h3>Paymaster (Gasless)</h3>
            <p>
              Arc Paymaster enables gasless transactions for users.
              Users can interact with vaults without holding native gas tokens.
            </p>
            <div className="feature-tag">Sponsor · ERC-4337</div>
          </div>
          <div className="feature-card">
            <div className="feature-icon">🔗</div>
            <h3>Gateway + USYC</h3>
            <p>
              Unified balance queries across chains. USYC yield token integration
              for vault floor enforcement per risk profile.
            </p>
            <div className="feature-tag">Nanopayments · Balance API</div>
          </div>
        </div>
      </section>

      {/* ─── CTA ─── */}
      <section className="landing-cta">
        <h2>Give me a lever long enough<br />and I shall move the world.</h2>
        <p className="cta-quote">— Archimedes (paraphrased)</p>
        <p className="cta-sub">
          The lever is academic research.<br/>
          The fulcrum is autonomous AI.<br/>
          The world is your portfolio.
        </p>
        <div className="hero-actions">
          {walletAddr ? (
            <button className="btn-primary" onClick={() => onNavigate('trade')}>
              Start Trading →
            </button>
          ) : (
            <button className="btn-primary" onClick={onConnect}>
              Connect Wallet
            </button>
          )}
        </div>
        <div className="cta-powered">
          Powered by <strong>Arc</strong> × <strong>Circle</strong> × <strong>Canteen</strong>
        </div>
      </section>
    </div>
  )
}
