-- Vigil: Load progress tracking
-- Tracks which parquet files have been loaded to enable resume on failure

CREATE TABLE IF NOT EXISTS load_progress (
    file_id TEXT PRIMARY KEY,           -- e.g., "20250727/08.parquet"
    rows_loaded INTEGER NOT NULL,
    loaded_at TIMESTAMPTZ DEFAULT NOW()
);

