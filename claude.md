# Vigil - Hyperliquid Trader Intelligence Engine

A data pipeline and analytics system that identifies and classifies traders on Hyperliquid based on their trading performance and behavior patterns.

## Tech Stack

- **Language**: Python 3.12+
- **Package Manager**: uv
- **Database**: TimescaleDB (PostgreSQL extension)
- **Data Processing**: Polars, PyArrow, Pandas
- **Storage**: AWS S3, local Parquet files
- **Task Runner**: just (justfile)

## Project Structure

```
src/vigil/           # Core library
  config.py          # Environment config (AWS, DB, paths)
  s3.py              # S3 client with requester-pays support
  transforms.py      # LZ4/JSON/msgpack parsing, Parquet I/O
  db.py              # Database connection and COPY loading

scripts/             # CLI entry points
  fetch_data.py      # Download fills from Hyperliquid S3 → Parquet
  load_to_db.py      # Load Parquet files → TimescaleDB

sql/                 # Database schema
  001_fills.sql      # Fills hypertable (partitioned by time)
  002_transformations.sql  # Views and trader_profiles table

notebooks/           # Jupyter analysis notebooks
docs/                # Architecture, vision, research documentation
data/                # Local data storage (gitignored)
```

## Commands

```bash
# Setup
uv sync                    # Install dependencies

# Data pipeline
just fetch-data            # Download from Hyperliquid S3
just load-data             # Load parquet → database

# Database (TigerDB cloud - default)
just db-query "SQL"        # Run SQL query
just db-migrate            # Run all sql/*.sql migrations
just db-reset              # Drop schema + re-migrate
just db-shell              # Interactive psql

# Database (local Docker)
just db-local-up           # Start local TimescaleDB
just db-local-down         # Stop local database
just db-local-query "SQL"  # Run SQL query locally
just db-local-migrate      # Run migrations locally
just db-local-reset        # Reset local database

# Utilities
just clean                 # Clear local data
just disk                  # Show data directory size
```

## Environment Variables

Required in `.env` (see `.env.example`):

- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` - S3 access
- `DATABASE_URL` - PostgreSQL connection string
- `PARQUET_S3` - Optional S3 path override for parquet storage

## Data Flow

```
Hyperliquid S3 (hl-mainnet-node-data/)
    ↓ fetch_data.py (LZ4 decompress, JSON parse)
Parquet files (local or S3)
    ↓ load_to_db.py (COPY command)
TimescaleDB fills hypertable
    ↓ SQL transformations
Trader profiles & analytics
```

## Key Conventions

- Column names: Hyperliquid uses camelCase, database uses snake_case (auto-converted in db.py)
- Dual storage: Code handles both local filesystem and S3 paths transparently
- Incremental: Scripts skip already-processed files
- Time column: `time` is in milliseconds (Unix epoch)

## Database Schema

The `fills` table is a TimescaleDB hypertable with indexes on:

- `(user_address, time)` - trader lookups
- `(coin, time)` - asset lookups
- `tid`, `twap_id`, `builder` - specific fill types

## Current Focus

- Data ingestion pipeline is operational
- Trader classification logic documented in `docs/VISION.md`
- Analysis notebooks contain exploratory work and metric calculations
