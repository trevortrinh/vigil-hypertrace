# Vigil Data Pipeline

data_dir := "data"

# =============================================================================
# CLOUD DB
# =============================================================================

db-query sql:
    #!/usr/bin/env bash
    source .env && psql "$DATABASE_URL" -c "{{sql}}"

db-shell:
    #!/usr/bin/env bash
    source .env && psql "$DATABASE_URL"

db-migrate:
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
# db-reset:
#   just db-query "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
#   just db-migrate

# =============================================================================
# LOCAL DB
# =============================================================================

db-local-up:
    docker compose up -d

db-local-down:
    docker compose down

db-local-query sql:
    docker exec vigil-timescaledb psql -U postgres -d vigil -c "{{sql}}"

db-local-shell:
    docker exec -it vigil-timescaledb psql -U postgres -d vigil

db-local-migrate:
    #!/usr/bin/env bash
    docker exec vigil-timescaledb psql -U postgres -d vigil -f /docker-entrypoint-initdb.d/001_fills.sql
    docker exec vigil-timescaledb psql -U postgres -d vigil -f /docker-entrypoint-initdb.d/002_load_tracking.sql

db-local-aggregates:
    docker exec vigil-timescaledb psql -U postgres -d vigil -f /docker-entrypoint-initdb.d/003_continuous_aggregates.sql

db-local-refresh:
    #!/usr/bin/env bash
    docker exec vigil-timescaledb psql -U postgres -d vigil -c "CALL refresh_continuous_aggregate('trader_daily', NULL, NULL);"
    docker exec vigil-timescaledb psql -U postgres -d vigil -c "CALL refresh_continuous_aggregate('coin_daily', NULL, NULL);"
    docker exec vigil-timescaledb psql -U postgres -d vigil -c "CALL refresh_continuous_aggregate('builder_daily', NULL, NULL);"
    docker exec vigil-timescaledb psql -U postgres -d vigil -c "REFRESH MATERIALIZED VIEW trader_profiles;"

db-local-stats:
    docker exec vigil-timescaledb psql -U postgres -d vigil -c "SELECT * FROM top_traders_by_type;"

db-local-reset:
    just db-local-query "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
    just db-local-migrate

# =============================================================================
# DATA
# =============================================================================

# S3 → parquet
fetch-data:
    uv run python scripts/fetch_data.py

# cloud DB → parquet (sample)
cloud-sample:
    uv run python scripts/cloud_sample.py

# parquet → cloud DB
cloud-load:
    uv run python scripts/cloud_load.py

# parquet → local DB
local-load:
    uv run python scripts/local_load.py

# =============================================================================
# UTILS
# =============================================================================

clean:
    rm -rf {{data_dir}}/*

disk:
    echo "data:" && du -sh {{data_dir}} 2>/dev/null || echo "  empty"
