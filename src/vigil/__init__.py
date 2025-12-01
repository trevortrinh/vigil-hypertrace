"""Vigil: Hyperliquid Trader Intelligence Engine."""

from vigil.config import DATA_DIR, DATABASE_URL, HL_BUCKET, HL_PREFIX, LOCAL_PARQUET_DIR
from vigil.db import execute_query, get_db_connection, load_parquet_to_db
from vigil.s3 import (
    download,
    download_hour,
    get_s3_client,
    list_available_hours,
    list_files,
    list_prefixes,
)
from vigil.transforms import (
    decompress_lz4,
    load_parquet,
    load_parquet_dir,
    parse_fills,
    parse_jsonl_lz4,
    parse_msgpack_lz4,
    save_parquet,
)

__all__ = [
    # Config
    "DATA_DIR",
    "DATABASE_URL",
    "HL_BUCKET",
    "HL_PREFIX",
    "LOCAL_PARQUET_DIR",
    # S3
    "get_s3_client",
    "download",
    "download_hour",
    "list_available_hours",
    "list_files",
    "list_prefixes",
    # Transforms
    "decompress_lz4",
    "load_parquet",
    "load_parquet_dir",
    "parse_fills",
    "parse_jsonl_lz4",
    "parse_msgpack_lz4",
    "save_parquet",
    # DB
    "execute_query",
    "get_db_connection",
    "load_parquet_to_db",
]
