-- Add persistent backtest results table.
-- Idempotent migration keyed by strategy_id + content_hash.

CREATE TABLE IF NOT EXISTS backtest_results (
    id INTEGER PRIMARY KEY,
    strategy_id VARCHAR(64) NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    run_id VARCHAR(32),
    operation VARCHAR(32),

    sharpe_ratio DOUBLE PRECISION NOT NULL DEFAULT 0,
    sortino_ratio DOUBLE PRECISION NOT NULL DEFAULT 0,
    max_drawdown DOUBLE PRECISION NOT NULL DEFAULT 0,
    cagr DOUBLE PRECISION NOT NULL DEFAULT 0,
    calmar_ratio DOUBLE PRECISION NOT NULL DEFAULT 0,

    win_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    profit_factor DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_trades INTEGER NOT NULL DEFAULT 0,
    avg_holding_period_days DOUBLE PRECISION NOT NULL DEFAULT 0,

    correlation_to_spy DOUBLE PRECISION NOT NULL DEFAULT 0,
    correlation_to_btc DOUBLE PRECISION NOT NULL DEFAULT 0,

    equity_curve_json TEXT NOT NULL DEFAULT '[]',
    monthly_returns_json TEXT NOT NULL DEFAULT '[]',

    backtest_start DATE,
    backtest_end DATE,

    paper_claimed_sharpe DOUBLE PRECISION,
    paper_claimed_cagr DOUBLE PRECISION,
    paper_claimed_max_dd DOUBLE PRECISION,

    deflated_sharpe_ratio DOUBLE PRECISION,
    dsr_p_value DOUBLE PRECISION,
    num_trials_in_selection INTEGER,
    pbo_score DOUBLE PRECISION,

    out_of_sample_sharpe DOUBLE PRECISION,
    walk_forward_train_fraction DOUBLE PRECISION NOT NULL DEFAULT 0.70,
    look_ahead_audit_passed BOOLEAN NOT NULL DEFAULT FALSE,

    backtest_engine VARCHAR(32),
    backtest_code_hash VARCHAR(64),
    transaction_cost_bps INTEGER NOT NULL DEFAULT 10,

    artifact_json TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_backtest_strategy_content
    ON backtest_results(strategy_id, content_hash);

CREATE INDEX IF NOT EXISTS ix_backtest_strategy_created
    ON backtest_results(strategy_id, created_at);
