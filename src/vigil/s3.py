"""S3 helpers for fetching Hyperliquid data."""

from collections.abc import Iterator

import boto3

from vigil.config import (
    AWS_ACCESS_KEY_ID,
    AWS_REGION,
    AWS_SECRET_ACCESS_KEY,
    HL_BUCKET,
    HL_PREFIX,
    REQUEST_PAYER,
)


def get_s3_client():
    """Get S3 client configured for Hyperliquid bucket access."""
    return boto3.client(
        "s3",
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION,
    )


def list_available_dates(s3=None) -> list[str]:
    """List all available dates in the Hyperliquid fills bucket.

    Returns:
        List of date strings in YYYYMMDD format, sorted ascending.
    """
    if s3 is None:
        s3 = get_s3_client()

    dates = []
    paginator = s3.get_paginator("list_objects_v2")

    for page in paginator.paginate(
        Bucket=HL_BUCKET,
        Prefix=f"{HL_PREFIX}/",
        Delimiter="/",
        **REQUEST_PAYER,
    ):
        for prefix in page.get("CommonPrefixes", []):
            # prefix looks like "node_fills_by_block/hourly/20250727/"
            date_str = prefix["Prefix"].rstrip("/").split("/")[-1]
            if date_str.isdigit() and len(date_str) == 8:
                dates.append(date_str)

    return sorted(dates)


def list_available_hours(s3, date_str: str) -> list[int]:
    """List available hours for a given date.

    Args:
        s3: S3 client
        date_str: Date in YYYYMMDD format

    Returns:
        List of hours (0-23) available for this date.
    """
    hours = []
    paginator = s3.get_paginator("list_objects_v2")

    for page in paginator.paginate(
        Bucket=HL_BUCKET,
        Prefix=f"{HL_PREFIX}/{date_str}/",
        **REQUEST_PAYER,
    ):
        for obj in page.get("Contents", []):
            # key looks like "node_fills_by_block/hourly/20250727/0.lz4"
            filename = obj["Key"].split("/")[-1]
            if filename.endswith(".lz4"):
                hour = int(filename.replace(".lz4", ""))
                hours.append(hour)

    return sorted(hours)


def iter_all_available(s3=None) -> Iterator[tuple[str, int]]:
    """Iterate over all available (date, hour) pairs.

    Yields:
        Tuples of (date_str, hour) for each available file.
    """
    if s3 is None:
        s3 = get_s3_client()

    for date_str in list_available_dates(s3):
        for hour in list_available_hours(s3, date_str):
            yield date_str, hour


def download_hour(s3, date_str: str, hour: int) -> bytes:
    """Download a single hour's fill data.

    Args:
        s3: S3 client
        date_str: Date in YYYYMMDD format
        hour: Hour (0-23)

    Returns:
        Raw LZ4 compressed bytes.
    """
    key = f"{HL_PREFIX}/{date_str}/{hour}.lz4"
    response = s3.get_object(Bucket=HL_BUCKET, Key=key, **REQUEST_PAYER)
    return response["Body"].read()


# =============================================================================
# Generic S3 helpers (for exploring any bucket)
# =============================================================================


def list_prefixes(bucket: str, prefix: str = "", s3=None) -> list[str]:
    """List folder prefixes in any S3 bucket."""
    if s3 is None:
        s3 = get_s3_client()
    r = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, Delimiter="/", **REQUEST_PAYER)
    return [p["Prefix"] for p in r.get("CommonPrefixes", [])]


def list_files(bucket: str, prefix: str, limit: int = 100, s3=None) -> list[tuple[str, int]]:
    """List files in any S3 bucket. Returns list of (key, size) tuples."""
    if s3 is None:
        s3 = get_s3_client()
    r = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=limit, **REQUEST_PAYER)
    return [(obj["Key"], obj["Size"]) for obj in r.get("Contents", [])]


def download(bucket: str, key: str, s3=None) -> bytes:
    """Download file from any S3 bucket."""
    if s3 is None:
        s3 = get_s3_client()
    return s3.get_object(Bucket=bucket, Key=key, **REQUEST_PAYER)["Body"].read()
