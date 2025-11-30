-- Vigil: Hyperliquid Trader Intelligence
-- TimescaleDB Schema

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- =============================================================================
-- FILLS TABLE (raw column names from S3)
-- =============================================================================

CREATE TABLE IF NOT EXISTS fills (
    time            BIGINT NOT NULL,             -- Unix timestamp in milliseconds
    "user"          TEXT NOT NULL,               -- User address (quoted - reserved word)
    coin            TEXT NOT NULL,
    px              TEXT NOT NULL,               -- Price (string for precision)
    sz              TEXT NOT NULL,               -- Size (string for precision)
    side            CHAR(1) NOT NULL,            -- 'B' buy, 'A' sell
    dir             TEXT,                        -- 'Open Long', 'Close Short', etc.
    "startPosition" TEXT,                        -- Position before fill
    "closedPnl"     TEXT,                        -- Realized PnL on closes
    fee             TEXT,                        -- Fee paid
    crossed         BOOLEAN,                     -- true=taker, false=maker
    hash            TEXT,                        -- Transaction hash
    oid             BIGINT,                      -- Order ID
    tid             BIGINT,                      -- Trade ID
    block_time      TEXT,                        -- Block timestamp (ISO string)
    "feeToken"      TEXT,                        -- e.g., 'USDC'
    "twapId"        BIGINT,                      -- TWAP order ID
    "builderFee"    TEXT,                        -- Builder fee
    cloid           TEXT,                        -- Client order ID
    builder         TEXT,                        -- Builder/frontend address
    liquidation     TEXT                         -- Liquidation info
);

-- Convert to hypertable partitioned by time (ms)
SELECT create_hypertable('fills', 'time',
    chunk_time_interval => 86400000,  -- 1 day in milliseconds
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_fills_user_time ON fills ("user", time DESC);
CREATE INDEX IF NOT EXISTS idx_fills_coin_time ON fills (coin, time DESC);
CREATE INDEX IF NOT EXISTS idx_fills_tid ON fills (tid);
CREATE INDEX IF NOT EXISTS idx_fills_twapId ON fills ("twapId") WHERE "twapId" IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fills_builder ON fills (builder) WHERE builder IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fills_liquidation ON fills (liquidation) WHERE liquidation IS NOT NULL;

-- =============================================================================
-- VIEWS (for convenience, not continuous aggregates)
-- =============================================================================

-- Daily trader stats view (query on demand)
CREATE OR REPLACE VIEW trader_daily AS
SELECT
    (time / 86400000) * 86400000 AS day,  -- Floor to day in ms
    "user",
    COUNT(*) AS fill_count,
    SUM(px::numeric * sz::numeric) AS volume,
    SUM(COALESCE("closedPnl"::numeric, 0)) AS realized_pnl,
    SUM(COALESCE(fee::numeric, 0)) AS fees_paid,
    AVG(CASE WHEN NOT crossed THEN 1 ELSE 0 END) AS maker_pct,
    SUM(CASE WHEN "closedPnl"::numeric > 0 THEN 1 ELSE 0 END) AS winning_trades,
    SUM(CASE WHEN "closedPnl"::numeric < 0 THEN 1 ELSE 0 END) AS losing_trades,
    COUNT(DISTINCT coin) AS unique_coins
FROM fills
GROUP BY day, "user";

-- =============================================================================
-- TRADER PROFILES (computed by analysis pipeline)
-- =============================================================================

CREATE TABLE IF NOT EXISTS trader_profiles (
    "user"              TEXT PRIMARY KEY,

    -- Activity
    first_trade         TIMESTAMPTZ,
    last_trade          TIMESTAMPTZ,
    active_days         INT,
    total_volume        NUMERIC(20,2),
    total_trades        INT,
    unique_coins        INT,

    -- Performance
    realized_pnl        NUMERIC(20,2),
    fees_paid           NUMERIC(20,2),
    net_pnl             NUMERIC(20,2),
    pnl_per_trade       NUMERIC(20,4),
    win_rate            NUMERIC(5,4),
    profit_factor       NUMERIC(10,4),

    -- Behavior
    maker_pct           NUMERIC(5,4),
    avg_hold_time_min   NUMERIC(10,2),
    avg_trade_size      NUMERIC(20,2),
    long_short_ratio    NUMERIC(10,4),

    -- Risk
    sharpe_ratio        NUMERIC(10,4),
    max_drawdown        NUMERIC(20,2),
    consistency         NUMERIC(10,4),

    -- Classification
    cluster_id          INT,
    cluster_name        TEXT,

    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_profiles_cluster ON trader_profiles (cluster_id);
CREATE INDEX IF NOT EXISTS idx_profiles_pnl ON trader_profiles (net_pnl DESC);
