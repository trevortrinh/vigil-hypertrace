# Vigil Data Pipeline

data_dir := "data"

# scripts
fetch-data:
    uv run python scripts/fetch_data.py

load-data:
    uv run python scripts/load_to_db.py

# db
db-up:
    docker compose up -d

db-down:
    docker compose down

db-reset:
    just db-query "DROP TABLE IF EXISTS fills CASCADE"
    docker exec vigil-timescaledb psql -U postgres -d vigil -f /docker-entrypoint-initdb.d/001_fills.sql
    docker exec vigil-timescaledb psql -U postgres -d vigil -f /docker-entrypoint-initdb.d/002_transformations.sql

db-query sql:
    docker exec vigil-timescaledb psql -U postgres -d vigil -c "{{sql}}"

# utils
clean:
    rm -rf {{data_dir}}/*

disk:
    echo "data:" && du -sh {{data_dir}} 2>/dev/null || echo "  empty"
