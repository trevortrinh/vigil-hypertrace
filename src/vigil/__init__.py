"""Vigil: Hyperliquid Trader Intelligence Engine."""

from vigil.config import DATABASE_URL, HL_BUCKET, HL_PREFIX, LOCAL_DATA_DIR, PARQUET_DIR
from vigil.db import execute_query, get_db_connection, load_dataframe_to_db, load_parquet_to_db
from vigil.s3 import (
    download,
    get_s3_client,
    list_files,
    list_prefixes,
)
from vigil.transforms import (
    decompress_lz4,
    is_s3_path,
    list_parquet_files,
    load_parquet,
    load_parquet_dir,
    parquet_exists,
    parse_fills,
    parse_jsonl_lz4,
    parse_msgpack_lz4,
    parse_s3_path,
    save_parquet,
)

__all__ = [
    # Config
    "LOCAL_DATA_DIR",
    "DATABASE_URL",
    "HL_BUCKET",
    "HL_PREFIX",
    "PARQUET_DIR",
    # S3
    "get_s3_client",
    "download",
    "list_files",
    "list_prefixes",
    # Transforms (with S3/local path support)
    "decompress_lz4",
    "is_s3_path",
    "list_parquet_files",
    "load_parquet",
    "load_parquet_dir",
    "parquet_exists",
    "parse_fills",
    "parse_jsonl_lz4",
    "parse_msgpack_lz4",
    "parse_s3_path",
    "save_parquet",
    # DB
    "execute_query",
    "get_db_connection",
    "load_dataframe_to_db",
    "load_parquet_to_db",
]
