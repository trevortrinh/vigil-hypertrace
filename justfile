# Vigil Data Pipeline

data_dir := "data"

# =============================================================================
# CLOUD DB
# =============================================================================

db-base:
    #!/usr/bin/env bash
    source .env
    psql "$DATABASE_URL" -f sql/001_fills.sql
    psql "$DATABASE_URL" -f sql/002_load_tracking.sql

db-aggregates:
    #!/usr/bin/env bash
    source .env
    psql "$DATABASE_URL" -f sql/003_continuous_aggregates.sql

db-refresh:
    #!/usr/bin/env bash
    source .env
    psql "$DATABASE_URL" -c "CALL refresh_continuous_aggregate('trader_daily', NULL, NULL);"
    psql "$DATABASE_URL" -c "CALL refresh_continuous_aggregate('coin_daily', NULL, NULL);"
    psql "$DATABASE_URL" -c "CALL refresh_continuous_aggregate('builder_daily', NULL, NULL);"
    psql "$DATABASE_URL" -c "REFRESH MATERIALIZED VIEW trader_profiles;"

# comment out to avoid resetting db
db-reset:
  just db-query "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
  just db-base

db-query sql:
    #!/usr/bin/env bash
    source .env && psql "$DATABASE_URL" -c "{{sql}}"

db-shell:
    #!/usr/bin/env bash
    source .env && psql "$DATABASE_URL"


# =============================================================================
# DATA
# =============================================================================

# S3 → parquet
fetch-data:
    uv run python scripts/fetch_data.py

# parquet → cloud DB
cloud-load:
    uv run python scripts/cloud_load.py

# =============================================================================
# UTILS
# =============================================================================

clean:
    rm -rf {{data_dir}}/*

disk:
    echo "data:" && du -sh {{data_dir}} 2>/dev/null || echo "  empty"
