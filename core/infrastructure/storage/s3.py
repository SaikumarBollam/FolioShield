"""
S3-compatible object storage backend (AWS S3, MinIO, Cloudflare R2, LocalStack).
"""

from typing import Any, Dict, List, Optional
from core.infrastructure.storage.base import StorageBackend, StorageError

try:
    import boto3
    from botocore.exceptions import ClientError
    _BOTO_AVAILABLE = True
except ImportError:
    boto3 = None  # type: ignore[assignment]
    ClientError = Exception  # type: ignore[misc, assignment]
    _BOTO_AVAILABLE = False


class S3StorageBackend(StorageBackend):
    """S3-compatible object storage backend."""

    def __init__(
        self,
        bucket_name: str,
        endpoint_url: Optional[str] = None,
        region_name: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        prefix: str = "folioshield",
    ) -> None:
        if not _BOTO_AVAILABLE:
            raise RuntimeError(
                "The boto3 package is required to use S3StorageBackend. "
                "Install it using 'pip install boto3'."
            )
        self.bucket_name = bucket_name
        self.prefix = prefix.strip("/")
        client_kwargs: Dict[str, Any] = {}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        if region_name:
            client_kwargs["region_name"] = region_name
        if aws_access_key_id and aws_secret_access_key:
            client_kwargs["aws_access_key_id"] = aws_access_key_id
            client_kwargs["aws_secret_access_key"] = aws_secret_access_key

        self._s3 = boto3.client("s3", **client_kwargs)

    def _s3_key(self, key: str, tenant_id: Optional[str] = None) -> str:
        parts: List[str] = []
        if self.prefix:
            parts.append(self.prefix)
        if tenant_id:
            parts.append(tenant_id)
        parts.append(key)
        return "/".join(parts)

    def put(
        self,
        key: str,
        data: bytes,
        metadata: Optional[Dict[str, str]] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        s3_key = self._s3_key(key, tenant_id)
        extra_args: Dict[str, Any] = {}
        if metadata:
            extra_args["Metadata"] = metadata
        try:
            self._s3.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=data,
                **extra_args,
            )
        except ClientError as exc:
            raise StorageError(f"Failed to put S3 object '{s3_key}': {exc}") from exc

    def get(self, key: str, tenant_id: Optional[str] = None) -> Optional[bytes]:
        s3_key = self._s3_key(key, tenant_id)
        try:
            response = self._s3.get_object(Bucket=self.bucket_name, Key=s3_key)
            return response["Body"].read()  # type: ignore[no-any-return]
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in ("NoSuchKey", "404"):
                # Fallback to unscoped key if tenant_id was given
                if tenant_id:
                    fallback_key = self._s3_key(key, tenant_id=None)
                    try:
                        resp = self._s3.get_object(Bucket=self.bucket_name, Key=fallback_key)
                        return resp["Body"].read()  # type: ignore[no-any-return]
                    except ClientError:
                        return None
                return None
            raise StorageError(f"Failed to get S3 object '{s3_key}': {exc}") from exc

    def has(self, key: str, tenant_id: Optional[str] = None) -> bool:
        s3_key = self._s3_key(key, tenant_id)
        try:
            self._s3.head_object(Bucket=self.bucket_name, Key=s3_key)
            return True
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in ("NoSuchKey", "404"):
                if tenant_id:
                    fallback_key = self._s3_key(key, tenant_id=None)
                    try:
                        self._s3.head_object(Bucket=self.bucket_name, Key=fallback_key)
                        return True
                    except ClientError:
                        return False
                return False
            raise StorageError(f"Failed to head S3 object '{s3_key}': {exc}") from exc

    def delete(self, key: str, tenant_id: Optional[str] = None) -> bool:
        s3_key = self._s3_key(key, tenant_id)
        try:
            self._s3.delete_object(Bucket=self.bucket_name, Key=s3_key)
            return True
        except ClientError as exc:
            raise StorageError(f"Failed to delete S3 object '{s3_key}': {exc}") from exc

    def list_keys(self, prefix: str = "", tenant_id: Optional[str] = None) -> List[str]:
        s3_prefix = self._s3_key(prefix, tenant_id)
        try:
            paginator = self._s3.get_paginator("list_objects_v2")
            keys: List[str] = []
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=s3_prefix):
                for item in page.get("Contents", []):
                    raw = item["Key"]
                    if tenant_id and f"{tenant_id}/" in raw:
                        raw = raw.split(f"{tenant_id}/", 1)[1]
                    elif self.prefix and f"{self.prefix}/" in raw:
                        raw = raw.split(f"{self.prefix}/", 1)[1]
                    keys.append(raw)
            return keys
        except ClientError as exc:
            raise StorageError(f"Failed to list S3 objects under '{s3_prefix}': {exc}") from exc
