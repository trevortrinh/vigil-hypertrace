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
) WITH (
    tsdb.hypertable,
    tsdb.partition_column = 'time',
    tsdb.chunk_interval = 86400000,              -- 1 day in milliseconds
    tsdb.columnstore,
    tsdb.segmentby = 'user_address',             -- Most common filter column
    tsdb.orderby = 'time DESC'
);

-- =============================================================================
-- COMPRESSION POLICY
-- =============================================================================
-- Automatically compress chunks older than 1 day (data is append-only)
CALL add_columnstore_policy('fills', after => INTERVAL '1 day');
