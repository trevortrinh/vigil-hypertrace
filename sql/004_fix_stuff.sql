-- =============================================================================
-- OPTIMIZATION: Pre-aggregated views for fast queries
-- =============================================================================
-- Run AFTER initial data load and continuous aggregate refresh completes.
-- See docs/05_query_optimization.md for usage guide.
-- =============================================================================

-- =============================================================================
-- PART 1: Fix Continuous Aggregate Refresh Policies
-- =============================================================================
-- Problem: NULL start_offset means every hourly refresh re-aggregates ALL data
-- Solution: Only refresh last 7 days (604800000 ms)

SELECT remove_continuous_aggregate_policy('trader_daily', if_exists => true);
SELECT remove_continuous_aggregate_policy('coin_daily', if_exists => true);
SELECT remove_continuous_aggregate_policy('builder_daily', if_exists => true);

SELECT add_continuous_aggregate_policy('trader_daily',
    start_offset => 604800000::bigint,  -- 7 days in ms
    end_offset => 3600000::bigint,       -- exclude last 1 hour
    schedule_interval => INTERVAL '1 hour'
);

SELECT add_continuous_aggregate_policy('coin_daily',
    start_offset => 604800000::bigint,
    end_offset => 3600000::bigint,
    schedule_interval => INTERVAL '1 hour'
);

SELECT add_continuous_aggregate_policy('builder_daily',
    start_offset => 604800000::bigint,
    end_offset => 3600000::bigint,
    schedule_interval => INTERVAL '1 hour'
);

-- =============================================================================
-- PART 2: Dataset Stats (instant global statistics)
-- =============================================================================
-- Replaces: SELECT COUNT(*), SUM(volume), etc FROM fills

CREATE MATERIALIZED VIEW IF NOT EXISTS dataset_stats AS
SELECT
    SUM(fill_count) as total_fills,
    COUNT(DISTINCT user_address) as total_traders,
    (SELECT COUNT(DISTINCT coin) FROM coin_daily) as total_coins,
    SUM(volume) as total_volume,
    SUM(realized_pnl) as total_pnl,
    SUM(fees_paid) as total_fees,
    MIN(day) as first_day,
    MAX(day) as last_day,
    ((MAX(day) - MIN(day)) / 86400000.0) as days_of_data
FROM trader_daily;

CREATE UNIQUE INDEX IF NOT EXISTS dataset_stats_idx ON dataset_stats((1));

-- =============================================================================
-- PART 3: Smart Money Users (small lookup table for fast joins)
-- =============================================================================
-- Replaces: JOIN trader_profiles WHERE trader_type = 'SMART_DIRECTIONAL'

CREATE MATERIALIZED VIEW IF NOT EXISTS smart_money_users AS
SELECT user_address
FROM trader_profiles
WHERE trader_type = 'SMART_DIRECTIONAL';

CREATE UNIQUE INDEX IF NOT EXISTS smart_money_users_addr_idx
ON smart_money_users(user_address);

-- =============================================================================
-- PART 4: Smart Money Daily (positioning signals)
-- =============================================================================
-- Pre-aggregated smart money activity by day.
-- Uses trader_daily joined with smart_money_users.
--
-- NOTE: This is a regular materialized view, not a continuous aggregate,
-- because it joins with smart_money_users which isn't a hypertable.
--
-- Uses open_long_count and open_short_count as proxies for direction bias
-- (volume columns not available in current trader_daily schema)

CREATE MATERIALIZED VIEW IF NOT EXISTS smart_money_daily AS
WITH smart_trader_daily AS (
    SELECT
        td.day,
        td.user_address,
        td.volume,
        td.realized_pnl,
        td.open_long_count,
        td.open_short_count,
        td.fill_count
    FROM trader_daily td
    WHERE EXISTS (
        SELECT 1 FROM smart_money_users s
        WHERE s.user_address = td.user_address
    )
)
SELECT
    day,
    COUNT(DISTINCT user_address) as trader_count,
    SUM(volume) as total_volume,
    SUM(realized_pnl) as total_pnl,
    SUM(open_long_count) as long_count,
    SUM(open_short_count) as short_count,
    SUM(fill_count) as fill_count,
    CASE
        WHEN SUM(open_long_count) + SUM(open_short_count) > 0
        THEN (SUM(open_long_count) - SUM(open_short_count))::float /
             (SUM(open_long_count) + SUM(open_short_count))::float
        ELSE 0
    END as net_bias  -- positive = more longs, negative = more shorts
FROM smart_trader_daily
GROUP BY day;

CREATE INDEX IF NOT EXISTS smart_money_daily_day_idx ON smart_money_daily(day DESC);

-- =============================================================================
-- PART 5: Maker/Taker Summary
-- =============================================================================
-- Replaces: SELECT CASE WHEN crossed... GROUP BY crossed FROM fills

CREATE MATERIALIZED VIEW IF NOT EXISTS maker_taker_stats AS
SELECT
    SUM(maker_fills) as maker_fills,
    SUM(taker_fills) as taker_fills,
    SUM(fill_count) as total_fills,
    ROUND(SUM(maker_fills)::numeric / NULLIF(SUM(fill_count), 0) * 100, 2) as maker_pct,
    ROUND(SUM(taker_fills)::numeric / NULLIF(SUM(fill_count), 0) * 100, 2) as taker_pct
FROM trader_daily;

-- =============================================================================
-- PART 6: Trader Type Summary
-- =============================================================================
-- Quick stats by trader classification

CREATE MATERIALIZED VIEW IF NOT EXISTS trader_type_stats AS
SELECT
    trader_type,
    COUNT(*) as trader_count,
    SUM(net_pnl) as total_pnl,
    SUM(total_volume) as total_volume,
    AVG(sharpe_ratio) FILTER (WHERE sharpe_ratio IS NOT NULL AND sharpe_ratio != 'NaN'::float) as avg_sharpe,
    AVG(win_rate) as avg_win_rate,
    AVG(maker_pct) as avg_maker_pct
FROM trader_profiles
GROUP BY trader_type;

-- =============================================================================
-- PART 7: Refresh Functions
-- =============================================================================

CREATE OR REPLACE FUNCTION refresh_smart_money_users()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY smart_money_users;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION refresh_dataset_stats()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW dataset_stats;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION refresh_smart_money_daily()
RETURNS void AS $$
BEGIN
    -- Must refresh smart_money_users first
    REFRESH MATERIALIZED VIEW CONCURRENTLY smart_money_users;
    REFRESH MATERIALIZED VIEW smart_money_daily;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION refresh_all_stats()
RETURNS void AS $$
BEGIN
    -- Refresh in dependency order
    REFRESH MATERIALIZED VIEW CONCURRENTLY trader_profiles;
    REFRESH MATERIALIZED VIEW CONCURRENTLY smart_money_users;
    REFRESH MATERIALIZED VIEW dataset_stats;
    REFRESH MATERIALIZED VIEW smart_money_daily;
    REFRESH MATERIALIZED VIEW maker_taker_stats;
    REFRESH MATERIALIZED VIEW trader_type_stats;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- PART 8: Convenience Views (no refresh needed, live queries)
-- =============================================================================

-- Top traders with all key metrics
CREATE OR REPLACE VIEW top_traders AS
SELECT
    user_address,
    trader_type,
    net_pnl,
    total_volume,
    sharpe_ratio,
    win_rate,
    maker_pct,
    trading_days,
    total_fills
FROM trader_profiles
WHERE trading_days >= 7  -- Minimum activity
ORDER BY net_pnl DESC;

-- Worst performers
CREATE OR REPLACE VIEW worst_traders AS
SELECT
    user_address,
    trader_type,
    net_pnl,
    total_volume,
    sharpe_ratio,
    win_rate,
    maker_pct,
    trading_days
FROM trader_profiles
WHERE trading_days >= 7
ORDER BY net_pnl ASC;

-- Smart money watchlist (high Sharpe smart directional)
CREATE OR REPLACE VIEW smart_money_watchlist AS
SELECT
    user_address,
    net_pnl,
    sharpe_ratio,
    win_rate,
    total_volume,
    trading_days
FROM trader_profiles
WHERE trader_type = 'SMART_DIRECTIONAL'
  AND sharpe_ratio >= 1.0
  AND trading_days >= 14
ORDER BY sharpe_ratio DESC;

-- =============================================================================
-- USAGE NOTES
-- =============================================================================
--
-- After running this migration:
--
-- 1. Global stats (instant):
--    SELECT * FROM dataset_stats;
--
-- 2. Maker/taker breakdown (instant):
--    SELECT * FROM maker_taker_stats;
--
-- 3. Stats by trader type (instant):
--    SELECT * FROM trader_type_stats;
--
-- 4. Best traders:
--    SELECT * FROM top_traders LIMIT 50;
--
-- 5. Worst traders:
--    SELECT * FROM worst_traders LIMIT 50;
--
-- 6. Smart money watchlist:
--    SELECT * FROM smart_money_watchlist;
--
-- 7. Smart money daily positioning:
--    SELECT * FROM smart_money_daily ORDER BY day DESC LIMIT 30;
--
-- 8. Refresh after data loads:
--    SELECT refresh_all_stats();
--    -- Or use: just db-refresh
--
-- =============================================================================
