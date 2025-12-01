"""Data transformation functions for Hyperliquid fills."""

import io
import json
from pathlib import Path
from typing import Iterator

import lz4.frame
import msgpack
import polars as pl

# =============================================================================
# S3/LOCAL PATH HELPERS
# =============================================================================


def is_s3_path(path: str | Path) -> bool:
    """Check if path is an S3 URI."""
    return str(path).startswith("s3://")


def parse_s3_path(path: str | Path) -> tuple[str, str]:
    """Parse s3://bucket/key into (bucket, key)."""
    path_str = str(path).replace("s3://", "")
    parts = path_str.split("/", 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else ""
    return bucket, key


def _get_s3_client():
    """Lazy import to avoid circular dependency."""
    from vigil.s3 import get_s3_client
    return get_s3_client()


# =============================================================================
# FILL PARSING
# =============================================================================


def parse_fills(lz4_data: bytes) -> list[dict]:
    """Parse LZ4 compressed fills data, keeping original S3 field names.

    Args:
        lz4_data: Raw LZ4 compressed bytes from S3.

    Returns:
        List of fill dictionaries with original field names.
    """
    decompressed = lz4.frame.decompress(lz4_data)
    lines = decompressed.decode("utf-8").strip().split("\n")

    fills = []
    for line in lines:
        if not line.strip():
            continue
        block = json.loads(line)
        block_time = block.get("block_time")

        for user, fill_data in block.get("events", []):
            fill = {**fill_data, "user": user, "block_time": block_time}
            fills.append(fill)

    return fills


def save_parquet(fills: list[dict], output_path: Path | str) -> int:
    """Save fills to a Parquet file (local or S3).

    Args:
        fills: List of fill dictionaries.
        output_path: Local path or S3 URI (s3://bucket/key.parquet).

    Returns:
        Number of fills saved.
    """
    if not fills:
        return 0

    # infer_schema_length=None scans all rows for consistent types
    df = pl.DataFrame(fills, infer_schema_length=None)

    if is_s3_path(output_path):
        # Write to S3
        bucket, key = parse_s3_path(output_path)
        buf = io.BytesIO()
        df.write_parquet(buf, compression="zstd")
        buf.seek(0)
        s3 = _get_s3_client()
        s3.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    else:
        # Write to local filesystem
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(output_path, compression="zstd")

    return len(fills)


def load_parquet(path: Path | str) -> pl.DataFrame:
    """Load a parquet file as a Polars DataFrame (local or S3).

    Args:
        path: Local path or S3 URI (s3://bucket/key.parquet).

    Returns:
        Polars DataFrame.
    """
    if is_s3_path(path):
        bucket, key = parse_s3_path(path)
        s3 = _get_s3_client()
        data = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        return pl.read_parquet(io.BytesIO(data))
    return pl.read_parquet(path)


def list_parquet_files(base_path: str | Path, date_filter: str = None) -> list[str]:
    """List parquet files from local directory or S3.

    Args:
        base_path: Local directory or S3 URI (s3://bucket/prefix).
        date_filter: Optional date folder filter (e.g., "20251101").

    Returns:
        List of paths (local paths or S3 URIs).
    """
    if is_s3_path(base_path):
        bucket, prefix = parse_s3_path(base_path)
        prefix = prefix.rstrip("/")
        if date_filter:
            prefix = f"{prefix}/{date_filter}"

        s3 = _get_s3_client()
        files = []
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                if obj["Key"].endswith(".parquet"):
                    files.append(f"s3://{bucket}/{obj['Key']}")
        return sorted(files)
    else:
        base = Path(base_path)
        if date_filter:
            pattern = f"{date_filter}/*.parquet"
        else:
            pattern = "**/*.parquet"
        return sorted(str(f) for f in base.glob(pattern))


def parquet_exists(path: str | Path) -> bool:
    """Check if a parquet file exists (local or S3).

    Args:
        path: Local path or S3 URI.

    Returns:
        True if file exists.
    """
    if is_s3_path(path):
        bucket, key = parse_s3_path(path)
        s3 = _get_s3_client()
        try:
            s3.head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False
    return Path(path).exists()


def load_parquet_dir(directory: Path | str, pattern: str = "**/*.parquet") -> pl.DataFrame:
    """Load all parquet files from a directory (local or S3).

    Args:
        directory: Directory containing parquet files (local or S3 URI).
        pattern: Glob pattern for finding parquet files (local only, ignored for S3).

    Returns:
        Combined Polars DataFrame.
    """
    if is_s3_path(directory):
        files = list_parquet_files(directory)
        if not files:
            return pl.DataFrame()
        return pl.concat([load_parquet(f) for f in files])
    else:
        directory = Path(directory)
        files = sorted(directory.glob(pattern))
        if not files:
            return pl.DataFrame()
        return pl.concat([pl.read_parquet(f) for f in files])


# =============================================================================
# Generic parsing helpers (for exploring raw S3 data)
# =============================================================================


def decompress_lz4(data: bytes) -> bytes:
    """Decompress LZ4 data."""
    return lz4.frame.decompress(data)


def parse_jsonl_lz4(data: bytes) -> Iterator[dict]:
    """Parse LZ4-compressed JSON lines."""
    for line in lz4.frame.decompress(data).decode().strip().split("\n"):
        if line:
            yield json.loads(line)


def parse_msgpack_lz4(data: bytes) -> list:
    """Parse LZ4-compressed MessagePack."""
    return msgpack.unpackb(lz4.frame.decompress(data), raw=False)
