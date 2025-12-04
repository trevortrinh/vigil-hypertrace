#!/usr/bin/env python3
"""
Deploy the HTTP proxy Lambda function to AWS.

This creates:
1. IAM role with basic Lambda execution permissions
2. Lambda function from lambda/http_proxy/handler.py

Usage:
    python scripts/deploy_lambda.py          # Deploy/update the Lambda
    python scripts/deploy_lambda.py --delete # Delete the Lambda and role

Prerequisites:
    - AWS credentials configured (aws configure or env vars)
    - boto3 installed (uv add boto3)
"""

import argparse
import io
import json
import time
import zipfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

FUNCTION_NAME = "vigil-http-proxy"
ROLE_NAME = "vigil-lambda-role"
REGION = "us-east-1"  # Same region as Hyperliquid for lower latency

# Minimal IAM policy for Lambda execution
ASSUME_ROLE_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }
    ],
}


def create_deployment_package() -> bytes:
    """Zip the Lambda handler code."""
    handler_path = Path(__file__).parent.parent / "lambda" / "http_proxy" / "handler.py"

    if not handler_path.exists():
        raise FileNotFoundError(f"Handler not found: {handler_path}")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(handler_path, "handler.py")

    return zip_buffer.getvalue()


def get_or_create_role(iam) -> str:
    """Get existing role or create new one. Returns role ARN."""
    try:
        response = iam.get_role(RoleName=ROLE_NAME)
        print(f"Using existing IAM role: {ROLE_NAME}")
        return response["Role"]["Arn"]
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchEntity":
            raise

    print(f"Creating IAM role: {ROLE_NAME}")
    response = iam.create_role(
        RoleName=ROLE_NAME,
        AssumeRolePolicyDocument=json.dumps(ASSUME_ROLE_POLICY),
        Description="Lambda execution role for Vigil HTTP proxy",
    )
    role_arn = response["Role"]["Arn"]

    # Attach basic execution policy (CloudWatch logs)
    iam.attach_role_policy(
        RoleName=ROLE_NAME,
        PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
    )

    # Wait for role to propagate
    print("Waiting for IAM role to propagate...")
    time.sleep(10)

    return role_arn


def deploy_lambda(lambda_client, role_arn: str, zip_bytes: bytes) -> str:
    """Create or update the Lambda function. Returns function ARN."""
    try:
        # Try to update existing function
        response = lambda_client.update_function_code(
            FunctionName=FUNCTION_NAME,
            ZipFile=zip_bytes,
        )
        print(f"Updated Lambda function: {FUNCTION_NAME}")
        return response["FunctionArn"]
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise

    # Create new function
    print(f"Creating Lambda function: {FUNCTION_NAME}")
    response = lambda_client.create_function(
        FunctionName=FUNCTION_NAME,
        Runtime="python3.12",
        Role=role_arn,
        Handler="handler.lambda_handler",
        Code={"ZipFile": zip_bytes},
        Description="HTTP proxy for IP rotation",
        Timeout=60,
        MemorySize=128,
        # Enable provisioned concurrency later if needed
    )
    return response["FunctionArn"]


def delete_lambda(lambda_client, iam):
    """Delete the Lambda function and IAM role."""
    # Delete Lambda
    try:
        lambda_client.delete_function(FunctionName=FUNCTION_NAME)
        print(f"Deleted Lambda function: {FUNCTION_NAME}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            print(f"Lambda function not found: {FUNCTION_NAME}")
        else:
            raise

    # Detach policy and delete role
    try:
        iam.detach_role_policy(
            RoleName=ROLE_NAME,
            PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
        )
        iam.delete_role(RoleName=ROLE_NAME)
        print(f"Deleted IAM role: {ROLE_NAME}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchEntity":
            print(f"IAM role not found: {ROLE_NAME}")
        else:
            raise


def test_lambda(lambda_client):
    """Test the Lambda with a simple request."""
    print("\nTesting Lambda function...")
    response = lambda_client.invoke(
        FunctionName=FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps({
            "url": "https://api.hyperliquid.xyz/info",
            "method": "POST",
            "payload": {"type": "meta"},
        }),
    )

    result = json.loads(response["Payload"].read())
    if result.get("statusCode") == 200:
        print("Lambda test successful!")
        body = json.loads(result["body"])
        print(f"  Universe has {len(body.get('universe', []))} coins")
    else:
        print(f"Lambda test failed: {result}")


def main():
    parser = argparse.ArgumentParser(description="Deploy HTTP proxy Lambda")
    parser.add_argument("--delete", action="store_true", help="Delete Lambda and role")
    parser.add_argument("--test", action="store_true", help="Test after deploy")
    parser.add_argument("--region", default=REGION, help=f"AWS region (default: {REGION})")
    args = parser.parse_args()

    iam = boto3.client("iam")
    lambda_client = boto3.client("lambda", region_name=args.region)

    if args.delete:
        delete_lambda(lambda_client, iam)
        return

    # Deploy
    role_arn = get_or_create_role(iam)
    zip_bytes = create_deployment_package()
    function_arn = deploy_lambda(lambda_client, role_arn, zip_bytes)

    print(f"\nDeployed: {function_arn}")
    print(f"Region: {args.region}")
    print("\nTo use in your code:")
    print(f'  LAMBDA_FUNCTION_NAME = "{FUNCTION_NAME}"')
    print(f'  LAMBDA_REGION = "{args.region}"')

    if args.test:
        # Wait for function to be active
        time.sleep(2)
        test_lambda(lambda_client)


if __name__ == "__main__":
    main()
