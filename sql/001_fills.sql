-- Vigil: Hyperliquid Trader Intelligence
-- Base fills table for raw data import

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- =============================================================================
-- FILLS TABLE (snake_case columns)
-- =============================================================================

CREATE TABLE IF NOT EXISTS fills (
    time            BIGINT NOT NULL,             -- Unix timestamp in milliseconds
    user_address    TEXT NOT NULL,               -- User wallet address
    coin            TEXT NOT NULL,
    px              TEXT NOT NULL,               -- Price (string for precision)
    sz              TEXT NOT NULL,               -- Size (string for precision)
    side            CHAR(1) NOT NULL,            -- 'B' buy, 'A' sell
    dir             TEXT,                        -- 'Open Long', 'Close Short', etc.
    start_position  TEXT,                        -- Position before fill
    closed_pnl      TEXT,                        -- Realized PnL on closes
    fee             TEXT,                        -- Fee paid
    crossed         BOOLEAN,                     -- true=taker, false=maker
    hash            TEXT,                        -- Transaction hash
    oid             BIGINT,                      -- Order ID
    tid             BIGINT,                      -- Trade ID
    block_time      TEXT,                        -- Block timestamp (ISO string)
    fee_token       TEXT,                        -- e.g., 'USDC'
    twap_id         BIGINT,                      -- TWAP order ID
    builder_fee     TEXT,                        -- Builder fee
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

CREATE INDEX IF NOT EXISTS idx_fills_user_time ON fills (user_address, time DESC);
CREATE INDEX IF NOT EXISTS idx_fills_coin_time ON fills (coin, time DESC);
CREATE INDEX IF NOT EXISTS idx_fills_tid ON fills (tid);
CREATE INDEX IF NOT EXISTS idx_fills_twap_id ON fills (twap_id) WHERE twap_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fills_builder ON fills (builder) WHERE builder IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fills_liquidation ON fills (liquidation) WHERE liquidation IS NOT NULL;
