"""
lambda_handler.py
-----------------
AWS Lambda entry point for production deployment.
Wraps the FastAPI app with Mangum — the ASGI adapter for Lambda.

API Gateway (HTTP API) → Lambda → Mangum → FastAPI

Deploy:
    1. Package the entire sda_platform directory as a Lambda zip or container image
    2. Set handler to: lambda_handler.handler
    3. Set all environment variables (SDA_ENV, CLERK_*, AURORA_*, SQS_*, S3_*)
    4. Set Lambda timeout to 30s (API routes are fast — pipeline runs are async via SQS)
    5. Attach IAM role with: SQS send, S3 read/write, Secrets Manager read, RDS connect

Note:
    The pipeline does NOT run inside Lambda synchronously.
    POST /pipeline/run drops a message on SQS and returns 202 immediately.
    A separate Lambda function (pipeline_lambda.py) handles the actual pipeline execution.
    That Lambda has a much longer timeout (15 min) and is triggered by SQS.
"""

from api.main import app

try:
    from mangum import Mangum
    handler = Mangum(app, lifespan="off")
except ImportError:
    # Mangum not installed — running locally
    handler = None
