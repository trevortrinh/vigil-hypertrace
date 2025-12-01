"""Database helpers for TimescaleDB."""

import io
from pathlib import Path

import polars as pl
import psycopg

from vigil.config import DATABASE_URL, FILL_COLUMNS, SQL_COLUMNS


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

    Args:
        df: Polars DataFrame with fill data.
        conn: Database connection.

    Returns:
        Number of rows loaded.
    """
    if df.is_empty():
        return 0

    # Ensure all columns exist
    for col in FILL_COLUMNS:
        if col not in df.columns:
            df = df.with_columns(pl.lit(None).alias(col))
    df = df.select(FILL_COLUMNS)

    # Build CSV for COPY
    csv_buffer = io.StringIO()
    csv_buffer.write("\t".join(FILL_COLUMNS) + "\n")

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
            f"COPY fills ({','.join(SQL_COLUMNS)}) FROM STDIN WITH (FORMAT text, HEADER true)"
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