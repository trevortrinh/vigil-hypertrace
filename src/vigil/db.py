"""Database helpers for TimescaleDB."""

import io
from pathlib import Path

import polars as pl
import psycopg

from vigil.config import DATABASE_URL

# Parquet column (from S3) -> DB column (snake_case)
PARQUET_TO_DB = {
    "time": "time",
    "user": "user_address",
    "coin": "coin",
    "px": "px",
    "sz": "sz",
    "side": "side",
    "dir": "dir",
    "startPosition": "start_position",
    "closedPnl": "closed_pnl",
    "fee": "fee",
    "crossed": "crossed",
    "hash": "hash",
    "oid": "oid",
    "tid": "tid",
    "block_time": "block_time",
    "feeToken": "fee_token",
    "twapId": "twap_id",
    "builderFee": "builder_fee",
    "cloid": "cloid",
    "builder": "builder",
    "liquidation": "liquidation",
}

# Ordered lists for COPY operations
PARQUET_COLUMNS = list(PARQUET_TO_DB.keys())
DB_COLUMNS = list(PARQUET_TO_DB.values())


def get_db_connection(autocommit: bool = False):
    """Get a database connection.

    Args:
        autocommit: Whether to enable autocommit mode.

    Returns:
        psycopg connection object.
    """
    conn = psycopg.connect(DATABASE_URL)
    conn.autocommit = autocommit
    return conn


def load_parquet_to_db(parquet_path: Path | str, conn) -> int:
    """Load a parquet file into the fills table using COPY.

    Args:
        parquet_path: Path to the parquet file.
        conn: Database connection.

    Returns:
        Number of rows loaded.
    """
    df = pl.read_parquet(parquet_path)
    return load_dataframe_to_db(df, conn)


def load_dataframe_to_db(df: pl.DataFrame, conn) -> int:
    """Load a Polars DataFrame into the fills table.

    Renames parquet columns (camelCase) to DB columns (snake_case).

    Args:
        df: Polars DataFrame with fill data.
        conn: Database connection.

    Returns:
        Number of rows loaded.
    """
    if df.is_empty():
        return 0

    # Ensure all parquet columns exist (add nulls for missing)
    for col in PARQUET_COLUMNS:
        if col not in df.columns:
            df = df.with_columns(pl.lit(None).alias(col))

    # Select and rename to DB columns
    df = df.select(PARQUET_COLUMNS).rename(PARQUET_TO_DB)

    # Build CSV for COPY
    csv_buffer = io.StringIO()
    csv_buffer.write("\t".join(DB_COLUMNS) + "\n")

    for row in df.iter_rows():
        values = []
        for val in row:
            if val is None:
                values.append("\\N")
            elif isinstance(val, bool):
                values.append("t" if val else "f")
            else:
                values.append(
                    str(val).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")
                )
        csv_buffer.write("\t".join(values) + "\n")

    csv_buffer.seek(0)

    with conn.cursor() as cur:
        with cur.copy(
            f"COPY fills ({','.join(DB_COLUMNS)}) FROM STDIN WITH (FORMAT text, HEADER true)"
        ) as copy:
            while data := csv_buffer.read(8192):
                copy.write(data)

    return len(df)


def execute_query(query: str, conn=None) -> pl.DataFrame:
    """Execute a SQL query and return results as a Polars DataFrame.

    Args:
        query: SQL query string.
        conn: Optional database connection. Creates one if not provided.

    Returns:
        Polars DataFrame with query results.
    """
    should_close = conn is None
    if conn is None:
        conn = get_db_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(query)
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            return pl.DataFrame(rows, schema=columns, orient="row")
    finally:
        if should_close:
            conn.close()
