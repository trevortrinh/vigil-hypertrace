"""Configuration and settings for Vigil."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Project root (where pyproject.toml lives)
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Hyperliquid S3 bucket
HL_BUCKET = "hl-mainnet-node-data"
HL_PREFIX = "node_fills_by_block/hourly"
REQUEST_PAYER = {"RequestPayer": "requester"}

# AWS
AWS_REGION = os.getenv("AWS_REGION")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

# Local data directory (always a Path, for notebooks)
LOCAL_DATA_DIR = PROJECT_ROOT / "data"

# Optional S3 override for scripts
# Set PARQUET_S3=s3://bucket/prefix to use S3 instead of local
PARQUET_S3 = os.getenv("PARQUET_S3")


def get_parquet_dir() -> str:
    """Get the parquet directory path (local or S3)."""
    if PARQUET_S3:
        return PARQUET_S3.rstrip("/")
    return str(LOCAL_DATA_DIR / HL_BUCKET / HL_PREFIX)


PARQUET_DIR = get_parquet_dir()

# Database
DATABASE_URL = os.getenv("DATABASE_URL")
