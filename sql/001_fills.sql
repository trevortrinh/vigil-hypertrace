-- Vigil: Hyperliquid Trader Intelligence
-- Base fills table for raw data import

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

-- =============================================================================
-- INDEXES
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_fills_user_time ON fills ("user", time DESC);
CREATE INDEX IF NOT EXISTS idx_fills_coin_time ON fills (coin, time DESC);
CREATE INDEX IF NOT EXISTS idx_fills_tid ON fills (tid);
CREATE INDEX IF NOT EXISTS idx_fills_twapId ON fills ("twapId") WHERE "twapId" IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fills_builder ON fills (builder) WHERE builder IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fills_liquidation ON fills (liquidation) WHERE liquidation IS NOT NULL;
