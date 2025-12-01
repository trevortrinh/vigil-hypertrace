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
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

# Local paths - always relative to project root
DATA_DIR = Path(os.getenv("DATA_DIR", PROJECT_ROOT / "data"))
LOCAL_PARQUET_DIR = DATA_DIR / HL_BUCKET / HL_PREFIX

# Database
DATABASE_URL = os.getenv("DATABASE_URL")

# Fill columns (raw names from Hyperliquid S3)
FILL_COLUMNS = [
    "time",
    "user",
    "coin",
    "px",
    "sz",
    "side",
    "dir",
    "startPosition",
    "closedPnl",
    "fee",
    "crossed",
    "hash",
    "oid",
    "tid",
    "block_time",
    "feeToken",
    "twapId",
    "builderFee",
    "cloid",
    "builder",
    "liquidation",
]

# SQL-safe column names (quoted where needed for reserved words/camelCase)
SQL_COLUMNS = [
    "time",
    '"user"',
    "coin",
    "px",
    "sz",
    "side",
    "dir",
    '"startPosition"',
    '"closedPnl"',
    "fee",
    "crossed",
    "hash",
    "oid",
    "tid",
    "block_time",
    '"feeToken"',
    '"twapId"',
    '"builderFee"',
    "cloid",
    "builder",
    "liquidation",
]
