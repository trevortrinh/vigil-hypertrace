# Vigil Data Pipeline

data_dir := "data"

# scripts
fetch-data:
    uv run python scripts/fetch_data.py

load-data:
    uv run python scripts/load_to_db.py

# db (tigerdb cloud - default)
db-query sql:
    #!/usr/bin/env bash
    source .env && psql "$DATABASE_URL" -c "{{sql}}"

db-migrate:
    #!/usr/bin/env bash
    source .env
    for f in sql/*.sql; do
        echo "Running $f..."
        psql "$DATABASE_URL" -f "$f"
    done

db-reset:
    just db-query "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
    just db-migrate

db-shell:
    #!/usr/bin/env bash
    source .env && psql "$DATABASE_URL"

# db-local (docker)
db-local-up:
    docker compose up -d

db-local-down:
    docker compose down

db-local-reset:
    just db-local-query "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
    just db-local-migrate

db-local-migrate:
    #!/usr/bin/env bash
    for f in sql/*.sql; do
        echo "Running $f..."
        docker exec vigil-timescaledb psql -U postgres -d vigil -f /docker-entrypoint-initdb.d/$(basename "$f")
    done

db-local-query sql:
    docker exec vigil-timescaledb psql -U postgres -d vigil -c "{{sql}}"

# utils
clean:
    rm -rf {{data_dir}}/*

disk:
    echo "data:" && du -sh {{data_dir}} 2>/dev/null || echo "  empty"
