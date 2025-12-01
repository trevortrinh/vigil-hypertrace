"""S3 helpers for fetching data."""

import boto3

from vigil.config import (
    AWS_ACCESS_KEY_ID,
    AWS_REGION,
    AWS_SECRET_ACCESS_KEY,
    REQUEST_PAYER,
)


def get_s3_client():
    """Get S3 client configured for requester-pays access."""
    return boto3.client(
        "s3",
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION,
    )


def list_prefixes(bucket: str, prefix: str = "", s3=None) -> list[str]:
    """List folder prefixes in an S3 bucket (paginated)."""
    if s3 is None:
        s3 = get_s3_client()

    prefixes = []
    paginator = s3.get_paginator("list_objects_v2")

    for page in paginator.paginate(
        Bucket=bucket,
        Prefix=prefix,
        Delimiter="/",
        **REQUEST_PAYER,
    ):
        for p in page.get("CommonPrefixes", []):
            prefixes.append(p["Prefix"])

    return prefixes


def list_files(bucket: str, prefix: str, s3=None, limit: int = None) -> list[tuple[str, int]]:
    """List files in an S3 bucket (paginated).

    Args:
        bucket: S3 bucket name.
        prefix: Key prefix to filter by.
        s3: Optional S3 client.
        limit: Optional max number of files to return.

    Returns:
        List of (key, size) tuples.
    """
    if s3 is None:
        s3 = get_s3_client()

    files = []
    paginator = s3.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix, **REQUEST_PAYER):
        for obj in page.get("Contents", []):
            files.append((obj["Key"], obj["Size"]))
            if limit and len(files) >= limit:
                return files

    return files


def download(bucket: str, key: str, s3=None) -> bytes:
    """Download file from an S3 bucket."""
    if s3 is None:
        s3 = get_s3_client()
    return s3.get_object(Bucket=bucket, Key=key, **REQUEST_PAYER)["Body"].read()
