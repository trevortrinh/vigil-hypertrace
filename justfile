# Vigil Data Pipeline

data_dir := "data"

# db
db-up:
    docker compose up -d

db-down:
    docker compose down

db-reset:
    just db-query "TRUNCATE fills CASCADE"
    just db-query "DROP MATERIALIZED VIEW IF EXISTS trader_daily CASCADE"
    docker exec vigil-timescaledb psql -U postgres -d vigil -f /docker-entrypoint-initdb.d/schema.sql

# utils
clean:
    rm -rf {{data_dir}}/*

disk:
    @echo "data:" && du -sh {{data_dir}} 2>/dev/null || echo "  empty"
