# Vigil Data Pipeline

data_dir := "data"

# Start TimescaleDB
up:
    @docker compose up -d

# Stop TimescaleDB
down:
    @docker compose down

# Fetch earliest data (2025-07-27, starts hour 8)
fetch-earliest hours="8-23" keep-raw="":
    @uv run python scripts/fetch_data.py --earliest --hours {{hours}} {{keep-raw}}

# Fetch specific date
fetch date hours="0-23" keep-raw="":
    @uv run python scripts/fetch_data.py --date {{date}} --hours {{hours}} {{keep-raw}}

# Fetch date range
fetch-range start end keep-raw="":
    @uv run python scripts/fetch_data.py --start {{start}} --end {{end}} {{keep-raw}}

# Load parquet into TimescaleDB
load date="":
    @uv run python scripts/load_to_db.py {{ if date != "" { "--date " + date } else { "" } }}

# Fetch and load
ingest date hours="0-23" keep-raw="":
    @just fetch {{date}} {{hours}} {{keep-raw}}
    @just load

# Query DB
query sql:
    @docker exec vigil-timescaledb psql -U postgres -d vigil -c "{{sql}}"

# Show stats
stats:
    @just query "SELECT COUNT(*) as fills, COUNT(DISTINCT user_address) as traders, COUNT(DISTINCT coin) as coins, SUM(price * size)::bigint as volume FROM fills"

# Top traders by PnL
top-traders n="10":
    @just query "SELECT user_address, COUNT(*)/2 as trades, SUM(closed_pnl)::int as pnl, (SUM(price*size)/2)::bigint as volume FROM fills GROUP BY user_address HAVING SUM(closed_pnl) > 1000 ORDER BY pnl DESC LIMIT {{n}}"

# Top losers
top-losers n="10":
    @just query "SELECT user_address, COUNT(*)/2 as trades, SUM(closed_pnl)::int as pnl, (SUM(price*size)/2)::bigint as volume FROM fills GROUP BY user_address HAVING SUM(closed_pnl) < -1000 ORDER BY pnl ASC LIMIT {{n}}"

# Volume by coin
top-coins n="10":
    @just query "SELECT coin, COUNT(*)/2 as trades, (SUM(price*size)/2)::bigint as volume, COUNT(DISTINCT user_address) as traders FROM fills GROUP BY coin ORDER BY volume DESC LIMIT {{n}}"

# Hourly volume
hourly-volume:
    @just query "SELECT time_bucket('1 hour', time) as hour, COUNT(*)/2 as trades, (SUM(price*size)/2)::bigint as volume FROM fills GROUP BY hour ORDER BY hour"

# Maker/taker breakdown
maker-taker:
    @just query "SELECT CASE WHEN crossed THEN 'Taker' ELSE 'Maker' END as type, COUNT(*) as fills, (SUM(price*size))::bigint as volume, SUM(fee)::int as fees FROM fills GROUP BY crossed"

# Trader lookup
trader addr:
    @just query "SELECT COUNT(*)/2 as trades, (SUM(price*size)/2)::bigint as volume, SUM(closed_pnl)::int as pnl, SUM(fee)::int as fees, COUNT(DISTINCT coin) as coins, ROUND(100.0*SUM(CASE WHEN NOT crossed THEN 1 ELSE 0 END)/COUNT(*),1) as maker_pct FROM fills WHERE user_address='{{addr}}'"

# Trader's coins
trader-coins addr:
    @just query "SELECT coin, COUNT(*)/2 as trades, (SUM(price*size)/2)::bigint as volume, SUM(closed_pnl)::int as pnl FROM fills WHERE user_address='{{addr}}' GROUP BY coin ORDER BY volume DESC LIMIT 10"

# Refresh continuous aggregate
refresh-agg:
    @just query "CALL refresh_continuous_aggregate('trader_daily', NULL, NULL)"

# Reset DB
reset-db:
    @just query "TRUNCATE fills CASCADE"
    @just query "DROP MATERIALIZED VIEW IF EXISTS trader_daily CASCADE"
    @docker exec vigil-timescaledb psql -U postgres -d vigil -f /docker-entrypoint-initdb.d/schema.sql

# Clean data
clean:
    rm -rf {{data_dir}}/parquet/* {{data_dir}}/raw/*

# List hours for date
list-hours date:
    @uv run python -c "import boto3,os;from dotenv import load_dotenv;load_dotenv();s3=boto3.client('s3',aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),region_name='us-east-2');r=s3.list_objects_v2(Bucket='hl-mainnet-node-data',Prefix='node_fills_by_block/hourly/{{date}}/',RequestPayer='requester');[print(f\"{o['Key'].split('/')[-1]} ({o['Size']/1024/1024:.1f}MB)\") for o in r.get('Contents',[])]"

# Disk usage
disk:
    @echo "Parquet:" && du -sh {{data_dir}}/parquet 2>/dev/null || echo "  empty"
    @echo "Raw:" && du -sh {{data_dir}}/raw 2>/dev/null || echo "  empty"
    @echo "Notebooks:" && du -sh {{data_dir}}/notebooks 2>/dev/null || echo "  empty"
