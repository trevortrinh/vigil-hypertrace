"""Data transformation functions for Hyperliquid fills."""

import json
from pathlib import Path
from typing import Iterator

import lz4.frame
import msgpack
import polars as pl


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
    """Save fills to a Parquet file.

    Args:
        fills: List of fill dictionaries.
        output_path: Path to save the parquet file.

    Returns:
        Number of fills saved.
    """
    if not fills:
        return 0

    output_path = Path(output_path)

    # infer_schema_length=None scans all rows for consistent types
    df = pl.DataFrame(fills, infer_schema_length=None)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(output_path, compression="zstd")
    return len(fills)


def load_parquet(path: Path | str) -> pl.DataFrame:
    """Load a parquet file as a Polars DataFrame.

    Args:
        path: Path to the parquet file.

    Returns:
        Polars DataFrame.
    """
    return pl.read_parquet(path)


def load_parquet_dir(directory: Path | str, pattern: str = "**/*.parquet") -> pl.DataFrame:
    """Load all parquet files from a directory.

    Args:
        directory: Directory containing parquet files.
        pattern: Glob pattern for finding parquet files.

    Returns:
        Combined Polars DataFrame.
    """
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
