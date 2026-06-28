"""
File storage abstraction.

Local dev writes uploaded files to MEDIA_ROOT and serves them via FastAPI's
StaticFiles mount at MEDIA_BASE_URL. Production swap-in point: replace
`save_file` with an S3 (boto3) or GCS upload and return the resulting public
or signed URL -- callers only depend on getting a URL string back.
"""
import os
import uuid

from fastapi import UploadFile

from app.config import get_settings

settings = get_settings()


def save_file(file: UploadFile, subfolder: str) -> str:
    folder = os.path.join(settings.MEDIA_ROOT, subfolder)
    os.makedirs(folder, exist_ok=True)

    ext = os.path.splitext(file.filename or "")[1] or ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(folder, filename)

    with open(path, "wb") as f:
        f.write(file.file.read())

    return f"{settings.MEDIA_BASE_URL}/{subfolder}/{filename}"

    # Production implementation (S3):
    #
    # import boto3
    # s3 = boto3.client("s3")
    # key = f"{subfolder}/{filename}"
    # s3.upload_fileobj(file.file, settings.S3_BUCKET, key)
    # return f"https://{settings.S3_BUCKET}.s3.amazonaws.com/{key}"
