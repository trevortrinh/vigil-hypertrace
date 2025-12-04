"""
AWS Lambda function for proxying HTTP requests.

Each Lambda invocation gets a different IP from AWS's pool,
enabling effective IP rotation for rate-limited APIs.

Deploy with: python scripts/deploy_lambda.py
"""

import json
import socket
import time
import urllib.request
import urllib.error


def get_outbound_ip():
    """Try to determine the Lambda's outbound IP."""
    try:
        # This makes a request to a service that returns our IP
        req = urllib.request.Request(
            "https://api.ipify.org?format=json",
            method="GET"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            return data.get("ip")
    except Exception:
        return None


def lambda_handler(event, context):
    """
    Proxy an HTTP request through Lambda.

    Event format:
    {
        "url": "https://api.example.com/endpoint",
        "method": "POST",  # optional, defaults to GET
        "payload": {...},  # optional, JSON body
        "headers": {...},  # optional
        "timeout": 30,     # optional, defaults to 30
        "include_meta": true  # optional, include debug metadata
    }

    Returns:
    {
        "statusCode": 200,
        "body": "...",  # response body as string
        "error": null,  # or error message
        "meta": {       # if include_meta=true
            "request_id": "...",
            "duration_ms": 123,
            "outbound_ip": "1.2.3.4",
            "lambda_ip": "10.x.x.x"
        }
    }
    """
    start_time = time.time()
    logs = []

    url = event.get("url")
    if not url:
        return {"statusCode": 400, "body": "", "error": "Missing 'url' parameter"}

    method = event.get("method", "GET").upper()
    payload = event.get("payload")
    headers = event.get("headers", {})
    timeout = event.get("timeout", 30)
    include_meta = event.get("include_meta", True)

    # Build request
    req = urllib.request.Request(url, method=method)

    # Add headers
    for key, value in headers.items():
        req.add_header(key, value)

    # Prepare body
    data = None
    if payload:
        data = json.dumps(payload).encode("utf-8")
        if "Content-Type" not in headers:
            req.add_header("Content-Type", "application/json")

    # Make the request
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            result = {
                "statusCode": resp.status,
                "body": body,
                "error": None,
            }
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        result = {
            "statusCode": e.code,
            "body": body,
            "error": f"HTTP {e.code}: {e.reason}",
        }
    except urllib.error.URLError as e:
        result = {
            "statusCode": 0,
            "body": "",
            "error": f"URL Error: {str(e.reason)}",
        }
    except Exception as e:
        result = {
            "statusCode": 0,
            "body": "",
            "error": f"Error: {str(e)}",
        }

    # Add metadata if requested
    if include_meta:
        duration_ms = int((time.time() - start_time) * 1000)

        # Get request ID from context
        request_id = getattr(context, 'aws_request_id', None) if context else None

        # Try to get Lambda's internal IP
        try:
            lambda_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            lambda_ip = None

        result["meta"] = {
            "request_id": request_id,
            "duration_ms": duration_ms,
            "lambda_ip": lambda_ip,
            "logs": logs,
        }

    return result
