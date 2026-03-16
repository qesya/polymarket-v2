-- ============================================================
-- Polymarket AI Trading System — Initial Schema
-- Run once: psql -U trader -d polymarket -f migrations/001_initial.sql
-- ============================================================

-- Extension for UUID support
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Markets ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS markets (
    id                  VARCHAR(100) PRIMARY KEY,
    question            TEXT NOT NULL,
    category            VARCHAR(50),
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    resolves_at         TIMESTAMPTZ,
    resolution          BOOLEAN,                    -- NULL until resolved
    resolved_at         TIMESTAMPTZ,
    last_price_yes      NUMERIC(10, 6),
    last_volume_24h     NUMERIC(20, 2) DEFAULT 0,
    volume_7d           NUMERIC(20, 2) DEFAULT 0,
    liquidity           NUMERIC(20, 2) DEFAULT 0,
    spread              NUMERIC(8, 6)  DEFAULT 0.05,
    volatility_7d       NUMERIC(8, 6)  DEFAULT 0,
    ttr_hours           NUMERIC(10, 2),
    market_age_days     NUMERIC(10, 2) DEFAULT 0,
    is_active           BOOLEAN DEFAULT TRUE,
    metadata            JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_markets_active ON markets (is_active, resolves_at);
CREATE INDEX IF NOT EXISTS idx_markets_resolution ON markets (resolution, resolved_at);
CREATE INDEX IF NOT EXISTS idx_markets_category ON markets (category);

-- ── Predictions ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS predictions (
    id                  BIGSERIAL PRIMARY KEY,
    market_id           VARCHAR(100) REFERENCES markets(id),
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    p_yes_xgb           NUMERIC(8, 6),
    p_yes_lgbm          NUMERIC(8, 6),
    p_yes_claude        NUMERIC(8, 6),
    p_yes_ensemble      NUMERIC(8, 6) NOT NULL,
    edge                NUMERIC(8, 6),
    market_price        NUMERIC(8, 6),
    confidence          NUMERIC(8, 6),
    feature_hash        VARCHAR(32),
    model_version       VARCHAR(30),
    data_quality        VARCHAR(10) DEFAULT 'HIGH',
    -- Research features (for retraining)
    sentiment_positive  NUMERIC(8, 6),
    sentiment_negative  NUMERIC(8, 6),
    sentiment_uncertainty NUMERIC(8, 6),
    social_momentum     NUMERIC(8, 6),
    narrative_intensity NUMERIC(8, 6),
    top_headlines       JSONB DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_predictions_market ON predictions (market_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_predictions_model ON predictions (model_version, created_at DESC);

-- ── Trades ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS trades (
    id                      BIGSERIAL PRIMARY KEY,
    idempotency_key         VARCHAR(64) UNIQUE NOT NULL,
    market_id               VARCHAR(100) REFERENCES markets(id),
    prediction_id           BIGINT REFERENCES predictions(id),
    placed_at               TIMESTAMPTZ DEFAULT NOW(),
    filled_at               TIMESTAMPTZ,
    side                    VARCHAR(3) NOT NULL CHECK (side IN ('YES', 'NO')),
    intended_shares         NUMERIC(20, 6),
    filled_shares           NUMERIC(20, 6) DEFAULT 0,
    intended_price          NUMERIC(8, 6),
    fill_price              NUMERIC(8, 6),
    slippage_bps            NUMERIC(8, 2) DEFAULT 0,
    dollar_size             NUMERIC(20, 2),
    pnl_realized            NUMERIC(20, 2),
    status                  VARCHAR(20) DEFAULT 'PENDING'
                                CHECK (status IN ('PENDING','FILLED','PARTIAL','CANCELLED','REJECTED')),
    order_id                VARCHAR(100),
    kelly_fraction          NUMERIC(8, 6),
    portfolio_value_at_trade NUMERIC(20, 2)
);

CREATE INDEX IF NOT EXISTS idx_trades_market ON trades (market_id);
CREATE INDEX IF NOT EXISTS idx_trades_placed ON trades (placed_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades (status);

-- ── Positions (current open positions) ────────────────────────────────────
CREATE TABLE IF NOT EXISTS positions (
    market_id           VARCHAR(100) PRIMARY KEY REFERENCES markets(id),
    side                VARCHAR(3) NOT NULL,
    total_shares        NUMERIC(20, 6) DEFAULT 0,
    avg_entry_price     NUMERIC(8, 6),
    current_price       NUMERIC(8, 6),
    unrealized_pnl      NUMERIC(20, 2) DEFAULT 0,
    realized_pnl        NUMERIC(20, 2) DEFAULT 0,
    opened_at           TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ── Postmortems ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS postmortems (
    id                  BIGSERIAL PRIMARY KEY,
    trade_id            BIGINT REFERENCES trades(id),
    market_id           VARCHAR(100) REFERENCES markets(id),
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    predicted_p_yes     NUMERIC(8, 6),
    actual_outcome      BOOLEAN,
    pnl                 NUMERIC(20, 2),
    mistake_category    VARCHAR(30),
    claude_analysis     TEXT,
    root_cause          TEXT,
    key_learning        TEXT,
    chroma_doc_id       VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_postmortems_category ON postmortems (mistake_category);
CREATE INDEX IF NOT EXISTS idx_postmortems_created ON postmortems (created_at DESC);

-- ── Model versions ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS model_versions (
    id                  BIGSERIAL PRIMARY KEY,
    version             VARCHAR(30) UNIQUE NOT NULL,
    deployed_at         TIMESTAMPTZ DEFAULT NOW(),
    xgb_brier_score     NUMERIC(8, 6),
    lgbm_brier_score    NUMERIC(8, 6),
    training_samples    INTEGER,
    is_active           BOOLEAN DEFAULT TRUE,
    notes               TEXT
);

-- ── PnL Daily Summary (materialized) ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS daily_pnl_summary (
    date                DATE PRIMARY KEY,
    total_trades        INTEGER DEFAULT 0,
    winning_trades      INTEGER DEFAULT 0,
    total_pnl           NUMERIC(20, 2) DEFAULT 0,
    largest_win         NUMERIC(20, 2) DEFAULT 0,
    largest_loss        NUMERIC(20, 2) DEFAULT 0,
    portfolio_value_eod NUMERIC(20, 2),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ── Utility function: update positions.updated_at on change ───────────────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_positions_updated
    BEFORE UPDATE ON positions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
