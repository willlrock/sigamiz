"""Stable photo keys, backed by a shared volume or S3 compatible storage."""
import os
import uuid
from urllib.parse import quote

UPLOAD_DIR = os.getenv("UPLOAD_DIR") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")


def s3_client():
    import boto3
    return boto3.client("s3", endpoint_url=os.getenv("S3_ENDPOINT_URL") or None)


def store_photo(data, upload_dir=UPLOAD_DIR):
    key = f"photos/{uuid.uuid4().hex}.jpg"
    if os.getenv("S3_BUCKET"):
        s3_client().put_object(Bucket=os.environ["S3_BUCKET"], Key=key, Body=data, ContentType="image/jpeg")
    else:
        path = os.path.join(upload_dir, *key.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as stream:
            stream.write(data)
    return key


def delete_photo(key, upload_dir=UPLOAD_DIR):
    if os.getenv("S3_BUCKET"):
        s3_client().delete_object(Bucket=os.environ["S3_BUCKET"], Key=key)
    else:
        try:
            os.remove(os.path.join(upload_dir, *key.split("/")))
        except FileNotFoundError:
            pass


def photo_url(path):
    path = str(path or "").replace("\\", "/")
    if path.startswith(("https://", "http://")):
        return path
    if "/uploads/" in path:
        path = path.split("/uploads/", 1)[1]
    path = path.lstrip("/")
    if os.getenv("S3_BUCKET") and path.startswith("photos/"):
        base = os.getenv("PHOTO_PUBLIC_URL")
        return f"{base.rstrip('/')}/{quote(path)}" if base else s3_client().generate_presigned_url("get_object", Params={"Bucket": os.environ["S3_BUCKET"], "Key": path}, ExpiresIn=3600)
    return f"/uploads/{quote(path)}" if path else None


def validate_storage():
    if (os.getenv("DEPLOYMENT_TOPOLOGY") == "split" or os.getenv('RAILWAY_PROJECT_ID')) and not os.getenv("S3_BUCKET") and os.getenv("SHARED_UPLOAD_VOLUME") != "true":
        raise RuntimeError("Split deployment requires S3_BUCKET or a shared UPLOAD_DIR with SHARED_UPLOAD_VOLUME=true")
