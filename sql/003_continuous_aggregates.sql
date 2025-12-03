-- Vigil: Pure SQL Analytics Pipeline
-- Everything computed in SQL - no Python needed for core metrics

-- =============================================================================
-- LEVEL 1: CONTINUOUS AGGREGATES (auto-refresh from fills)
-- =============================================================================

-- Trader daily stats
CREATE MATERIALIZED VIEW IF NOT EXISTS trader_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(86400000::bigint, time) AS day,
    user_address,

    -- Activity
    COUNT(*) AS fill_count,
    SUM((px::numeric) * (sz::numeric)) AS volume,
    COUNT(DISTINCT coin) AS unique_coins,

    -- PnL
    SUM(COALESCE(closed_pnl::numeric, 0)) AS realized_pnl,
    SUM(COALESCE(fee::numeric, 0)) AS fees_paid,
    SUM(COALESCE(builder_fee::numeric, 0)) AS builder_fees_paid,

    -- Maker/Taker
    SUM(CASE WHEN crossed THEN 1 ELSE 0 END) AS taker_fills,
    SUM(CASE WHEN NOT crossed THEN 1 ELSE 0 END) AS maker_fills,

    -- Win/Loss
    SUM(CASE WHEN closed_pnl::numeric > 0 THEN 1 ELSE 0 END) AS winning_fills,
    SUM(CASE WHEN closed_pnl::numeric < 0 THEN 1 ELSE 0 END) AS losing_fills,
    SUM(CASE WHEN closed_pnl::numeric != 0 THEN 1 ELSE 0 END) AS closing_fills,

    -- Direction
    SUM(CASE WHEN dir LIKE 'Open Long%' THEN 1 ELSE 0 END) AS open_long_count,
    SUM(CASE WHEN dir LIKE 'Open Short%' THEN 1 ELSE 0 END) AS open_short_count,

    -- Liquidations
    SUM(CASE WHEN liquidation IS NOT NULL THEN 1 ELSE 0 END) AS liquidation_fills,
    SUM(CASE WHEN liquidation IS NOT NULL THEN (px::numeric) * (sz::numeric) ELSE 0 END) AS liquidation_volume,

    -- TWAP
    SUM(CASE WHEN twap_id IS NOT NULL THEN 1 ELSE 0 END) AS twap_fills,
    SUM(CASE WHEN twap_id IS NOT NULL THEN (px::numeric) * (sz::numeric) ELSE 0 END) AS twap_volume

FROM fills
GROUP BY day, user_address
WITH NO DATA;

SELECT add_continuous_aggregate_policy('trader_daily',
    start_offset => NULL,
    end_offset => 3600000::bigint,
    schedule_interval => INTERVAL '1 hour'
);


-- Coin daily stats
CREATE MATERIALIZED VIEW IF NOT EXISTS coin_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(86400000::bigint, time) AS day,
    coin,

    COUNT(*) AS fill_count,
    COUNT(DISTINCT user_address) AS unique_traders,
    SUM((px::numeric) * (sz::numeric)) AS volume,

    -- Buy/Sell
    SUM(CASE WHEN dir LIKE 'Open Long%' OR dir LIKE 'Close Short%'
        THEN (px::numeric) * (sz::numeric) ELSE 0 END) AS buy_volume,
    SUM(CASE WHEN dir LIKE 'Open Short%' OR dir LIKE 'Close Long%'
        THEN (px::numeric) * (sz::numeric) ELSE 0 END) AS sell_volume,

    -- PnL & Fees
    SUM(COALESCE(closed_pnl::numeric, 0)) AS total_pnl,
    SUM(COALESCE(fee::numeric, 0)) AS total_fees,

    -- Liquidations
    SUM(CASE WHEN liquidation IS NOT NULL THEN 1 ELSE 0 END) AS liquidation_count,
    SUM(CASE WHEN liquidation IS NOT NULL THEN (px::numeric) * (sz::numeric) ELSE 0 END) AS liquidation_volume

FROM fills
GROUP BY day, coin
WITH NO DATA;

SELECT add_continuous_aggregate_policy('coin_daily',
    start_offset => NULL,
    end_offset => 3600000::bigint,
    schedule_interval => INTERVAL '1 hour'
);


-- Builder daily stats
CREATE MATERIALIZED VIEW IF NOT EXISTS builder_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(86400000::bigint, time) AS day,
    COALESCE(builder, 'direct') AS builder,

    COUNT(*) AS fill_count,
    COUNT(DISTINCT user_address) AS unique_traders,
    SUM((px::numeric) * (sz::numeric)) AS volume,
    SUM(COALESCE(fee::numeric, 0)) AS total_fees,
    SUM(COALESCE(builder_fee::numeric, 0)) AS builder_fees

FROM fills
GROUP BY day, COALESCE(builder, 'direct')
WITH NO DATA;

SELECT add_continuous_aggregate_policy('builder_daily',
    start_offset => NULL,
    end_offset => 3600000::bigint,
    schedule_interval => INTERVAL '1 hour'
);


-- =============================================================================
-- LEVEL 2: TRADER PROFILES (materialized view over trader_daily)
-- Computes Sharpe, classification - all in SQL
-- =============================================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS trader_profiles AS
WITH lifetime AS (
    SELECT
        user_address,

        -- Activity
        MIN(day) AS first_trade_time,
        MAX(day) AS last_trade_time,
        COUNT(DISTINCT day) AS trading_days,
        SUM(fill_count) AS total_fills,
        SUM(volume) AS total_volume,
        MAX(unique_coins) AS unique_coins,

        -- PnL
        SUM(realized_pnl) AS realized_pnl,
        SUM(fees_paid) AS fees_paid,
        SUM(builder_fees_paid) AS builder_fees_paid,
        SUM(realized_pnl) - SUM(fees_paid) - SUM(builder_fees_paid) AS net_pnl,

        -- Maker %
        SUM(maker_fills)::numeric / NULLIF(SUM(fill_count), 0) AS maker_pct,

        -- Win rate
        SUM(winning_fills)::numeric / NULLIF(SUM(closing_fills), 0) AS win_rate,

        -- MTM/TV (edge per dollar)
        SUM(realized_pnl) / NULLIF(SUM(volume), 0) AS mtm_tv,

        -- Long ratio
        SUM(open_long_count)::numeric / NULLIF(SUM(open_long_count) + SUM(open_short_count), 0) AS long_ratio,

        -- Liquidation stats
        SUM(liquidation_fills) AS liquidation_fills,
        SUM(liquidation_volume) AS liquidation_volume,
        SUM(liquidation_fills)::numeric / NULLIF(SUM(fill_count), 0) AS liquidation_pct,

        -- TWAP stats
        SUM(twap_fills) AS twap_fills,
        SUM(twap_volume) AS twap_volume,
        SUM(twap_volume) / NULLIF(SUM(volume), 0) AS twap_pct,

        -- For Sharpe calculation
        AVG(realized_pnl) AS avg_daily_pnl,
        STDDEV(realized_pnl) AS stddev_daily_pnl

    FROM trader_daily
    GROUP BY user_address
),
with_sharpe AS (
    SELECT
        *,
        -- Annualized Sharpe ratio
        CASE
            WHEN stddev_daily_pnl > 0 AND trading_days >= 2
            THEN (avg_daily_pnl / stddev_daily_pnl) * SQRT(365)
            ELSE 0
        END AS sharpe_ratio
    FROM lifetime
)
SELECT
    user_address,
    first_trade_time,
    last_trade_time,
    trading_days,
    total_fills,
    total_volume,
    unique_coins,
    realized_pnl,
    fees_paid,
    builder_fees_paid,
    net_pnl,
    maker_pct,
    win_rate,
    mtm_tv,
    long_ratio,
    liquidation_fills,
    liquidation_volume,
    liquidation_pct,
    twap_fills,
    twap_volume,
    twap_pct,
    sharpe_ratio,

    -- Classification (pure SQL)
    CASE
        WHEN liquidation_pct >= 0.20 THEN 'LIQUIDATOR'
        WHEN maker_pct >= 0.70 AND ABS(mtm_tv) <= 0.001 THEN 'HFT'
        WHEN net_pnl >= 100000 AND mtm_tv >= 0.001 AND sharpe_ratio >= 1.0 THEN 'SMART_DIRECTIONAL'
        ELSE 'RETAIL'
    END AS trader_type,

    NOW() AS updated_at

FROM with_sharpe;

-- Indexes for fast queries
CREATE UNIQUE INDEX IF NOT EXISTS idx_profiles_user ON trader_profiles (user_address);
CREATE INDEX IF NOT EXISTS idx_profiles_type ON trader_profiles (trader_type);
CREATE INDEX IF NOT EXISTS idx_profiles_pnl ON trader_profiles (net_pnl DESC);
CREATE INDEX IF NOT EXISTS idx_profiles_volume ON trader_profiles (total_volume DESC);
CREATE INDEX IF NOT EXISTS idx_profiles_sharpe ON trader_profiles (sharpe_ratio DESC);


-- =============================================================================
-- REFRESH FUNCTION (call periodically or after data loads)
-- =============================================================================

CREATE OR REPLACE FUNCTION refresh_trader_profiles()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY trader_profiles;
END;
$$ LANGUAGE plpgsql;


-- =============================================================================
-- CONVENIENCE VIEWS (live queries, no refresh needed)
-- =============================================================================

-- Top traders by type
CREATE OR REPLACE VIEW top_traders_by_type AS
SELECT
    trader_type,
    COUNT(*) as trader_count,
    SUM(total_volume) as total_volume,
    SUM(net_pnl) as total_pnl,
    AVG(sharpe_ratio) as avg_sharpe,
    AVG(maker_pct) as avg_maker_pct
FROM trader_profiles
GROUP BY trader_type
ORDER BY total_volume DESC;


-- Smart money activity (for signals)
CREATE OR REPLACE VIEW smart_money_positions AS
SELECT
    f.coin,
    DATE_TRUNC('hour', TO_TIMESTAMP(f.time / 1000)) as hour,
    SUM(CASE WHEN f.dir LIKE 'Open Long%' THEN (f.px::numeric * f.sz::numeric) ELSE 0 END) as smart_long_volume,
    SUM(CASE WHEN f.dir LIKE 'Open Short%' THEN (f.px::numeric * f.sz::numeric) ELSE 0 END) as smart_short_volume,
    COUNT(DISTINCT f.user_address) as smart_trader_count
FROM fills f
JOIN trader_profiles p ON f.user_address = p.user_address
WHERE p.trader_type = 'SMART_DIRECTIONAL'
GROUP BY f.coin, DATE_TRUNC('hour', TO_TIMESTAMP(f.time / 1000));


-- Recent liquidations
CREATE OR REPLACE VIEW recent_liquidations AS
SELECT
    f.time,
    f.coin,
    f.user_address as liquidator,
    f.px::numeric as price,
    f.sz::numeric as size,
    (f.px::numeric * f.sz::numeric) as notional,
    f.liquidation::json->>'liquidatedUser' as liquidated_user,
    f.liquidation::json->>'markPx' as mark_price,
    f.liquidation::json->>'method' as method
FROM fills f
WHERE f.liquidation IS NOT NULL
ORDER BY f.time DESC;
