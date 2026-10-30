"""Explicit local-only bucket initialization. Never grants public access."""

from botocore.exceptions import ClientError

from app.config import get_settings
from app.storage import s3_client


def setup_bucket(bucket: str) -> None:
    settings = get_settings()
    client = s3_client()
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") not in {
            "404",
            "NoSuchBucket",
            "NotFound",
        }:
            raise
        client.create_bucket(Bucket=bucket)
    acl = client.get_bucket_acl(Bucket=bucket)
    if any(
        grant.get("Grantee", {}).get("Type") == "Group"
        for grant in acl.get("Grants", [])
    ):
        raise ValueError(
            "Bucket ACL grants group access; verify privacy before using it"
        )
    # RustFS creates private buckets by default. No ACL or policy is added.
    # Refuse existing public policies rather than silently changing user policy.
    try:
        policy = client.get_bucket_policy(Bucket=bucket)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") not in {
            "NoSuchBucketPolicy",
            "404",
            "NotFound",
        }:
            raise
    else:
        if policy.get("Policy"):
            raise ValueError(
                "Bucket has an existing policy; verify its privacy before using it"
            )
    client.put_bucket_cors(
        Bucket=bucket,
        CORSConfiguration={
            "CORSRules": [
                {
                    "AllowedOrigins": sorted(settings.origins),
                    "AllowedMethods": ["PUT", "GET", "HEAD"],
                    "AllowedHeaders": ["content-type", "content-length"],
                    "ExposeHeaders": ["ETag"],
                    "MaxAgeSeconds": 300,
                }
            ]
        },
    )


def main() -> None:
    settings = get_settings()
    if (
        not settings.test_s3_bucket.endswith("-test")
        or settings.test_s3_bucket == settings.s3_bucket
    ):
        raise ValueError("TEST_S3_BUCKET must be a distinct bucket ending in -test")
    setup_bucket(settings.s3_bucket)
    setup_bucket(settings.test_s3_bucket)
    print(
        "Private development and isolated test buckets ready; trusted-origin CORS configured."
    )


if __name__ == "__main__":
    try:
        main()
    except (ClientError, ValueError):
        raise SystemExit(
            "Storage setup failed; verify private bucket configuration and connectivity."
        ) from None
