"""S3-compatible snapshot backend with optimistic index protection."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from urllib.parse import urlsplit

from .filesystem import SNAPSHOT_VERSION, canonical_url, diff_details, normalize_content, timestamp_slug


NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}
PRECONDITION_CODES = {"412", "ConditionalRequestConflict", "PreconditionFailed"}


def parse_s3_uri(value: object) -> tuple[str, str]:
    raw = str(value)
    parsed = urlsplit(raw)
    if parsed.scheme != "s3" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("S3 store must use s3://bucket/optional-prefix")
    if parsed.username or parsed.password:
        raise ValueError("S3 store URI must not contain credentials")
    prefix = parsed.path.strip("/")
    if any(part in {".", ".."} for part in prefix.split("/") if part):
        raise ValueError("S3 store prefix must not contain dot segments")
    return parsed.netloc, prefix


def validate_endpoint_url(value: str) -> str:
    parsed = urlsplit(value)
    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (
        (parsed.scheme != "https" and not local_http)
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("S3 endpoint must be HTTPS (or local HTTP) without credentials, query, or fragment")
    return value.rstrip("/")


def _error_code(exc: BaseException) -> str | None:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return None
    error = response.get("Error")
    if isinstance(error, dict) and error.get("Code") is not None:
        return str(error["Code"])
    metadata = response.get("ResponseMetadata")
    if isinstance(metadata, dict) and metadata.get("HTTPStatusCode") is not None:
        return str(metadata["HTTPStatusCode"])
    return None


class S3SnapshotStore:
    """Persist public page snapshots in an S3 bucket without storing credentials."""

    backend_name = "s3"

    def __init__(
        self,
        root: object,
        *,
        client=None,
        endpoint_url: str | None = None,
        region_name: str | None = None,
        max_index_retries: int = 3,
    ):
        self.bucket, self.prefix = parse_s3_uri(root)
        if max_index_retries < 1:
            raise ValueError("S3 max_index_retries must be positive")
        self.max_index_retries = max_index_retries
        if client is None:
            try:
                import boto3
            except ImportError as exc:
                raise ValueError("S3 backend requires the optional 's3' dependency") from exc
            options = {}
            if endpoint_url:
                options["endpoint_url"] = validate_endpoint_url(endpoint_url)
            if region_name:
                if not region_name.strip():
                    raise ValueError("S3 region name must not be blank")
                options["region_name"] = region_name.strip()
            client = boto3.client("s3", **options)
        self.client = client

    def _key(self, relative: str) -> str:
        return f"{self.prefix}/{relative}" if self.prefix else relative

    @staticmethod
    def _page_key(platform: str, canonical: str) -> str:
        return hashlib.sha256(f"{platform.casefold()}\n{canonical}".encode("utf-8")).hexdigest()[:20]

    def _get_json(self, key: str) -> tuple[dict | None, str | None]:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except BaseException as exc:
            if _error_code(exc) in NOT_FOUND_CODES:
                return None, None
            raise
        body = response["Body"]
        raw = body.read() if hasattr(body, "read") else body
        value = json.loads(bytes(raw).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"S3 object is not a JSON object: {key}")
        etag = response.get("ETag")
        return value, str(etag) if etag is not None else None

    def _put(
        self,
        key: str,
        content: bytes,
        content_type: str,
        *,
        etag: str | None = None,
        create_only: bool = False,
    ) -> None:
        arguments = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": content,
            "ContentType": content_type,
            "ServerSideEncryption": "AES256",
        }
        if create_only:
            arguments["IfNoneMatch"] = "*"
        elif etag is not None:
            arguments["IfMatch"] = etag
        else:
            arguments["IfNoneMatch"] = "*"
        self.client.put_object(**arguments)

    def _record_key(self, page_key: str, snapshot_id: str) -> str:
        return self._key(f"pages/{page_key}/snapshots/{snapshot_id}.json")

    def _diff_key(self, page_key: str, snapshot_id: str) -> str:
        return self._key(f"pages/{page_key}/diffs/{snapshot_id}.diff.txt")

    def _index_key(self, page_key: str) -> str:
        return self._key(f"pages/{page_key}/index.json")

    def _list_keys(self) -> list[str]:
        prefix = self._key("pages/")
        keys: list[str] = []
        token = None
        while True:
            arguments = {"Bucket": self.bucket, "Prefix": prefix}
            if token is not None:
                arguments["ContinuationToken"] = token
            response = self.client.list_objects_v2(**arguments)
            for item in response.get("Contents", []):
                key = item.get("Key") if isinstance(item, dict) else None
                if isinstance(key, str):
                    keys.append(key)
            if not response.get("IsTruncated"):
                return sorted(set(keys))
            token = response.get("NextContinuationToken")
            if not isinstance(token, str) or not token:
                raise ValueError("S3 listing is truncated without a continuation token")

    def _metadata(self, record: dict, page_key: str, has_diff: bool) -> dict:
        snapshot_key = self._record_key(page_key, record["snapshot_id"])
        diff_key = self._diff_key(page_key, record["snapshot_id"]) if has_diff else None
        return {
            "snapshot_id": record["snapshot_id"],
            "captured_at": record["captured_at"],
            "content_hash": record["content_hash"],
            "previous_snapshot_id": record.get("previous_snapshot_id"),
            "change_status": record["change_status"],
            "diff_summary": record["diff_summary"],
            "snapshot_path": f"s3://{self.bucket}/{snapshot_key}",
            "diff_path": f"s3://{self.bucket}/{diff_key}" if diff_key else None,
            "storage_backend": self.backend_name,
            "snapshot_ref": snapshot_key,
            "diff_ref": diff_key,
            "index_recovered": False,
        }

    def load_latest(self, platform: str, url: str) -> dict | None:
        if not isinstance(platform, str) or not platform.strip():
            raise ValueError("platform must not be blank")
        canonical = canonical_url(url)
        page_key = self._page_key(platform, canonical)
        index, _etag = self._get_json(self._index_key(page_key))
        if index is None:
            return None
        snapshot_id = index.get("latest_snapshot_id")
        if not isinstance(snapshot_id, str) or not snapshot_id:
            raise ValueError("S3 page index has no valid latest_snapshot_id")
        record, _record_etag = self._get_json(self._record_key(page_key, snapshot_id))
        if record is None:
            raise ValueError("S3 page index references a missing snapshot")
        return record

    def capture(self, platform: str, url: str, content: str, captured_at: str) -> dict:
        if not isinstance(platform, str) or not platform.strip():
            raise ValueError("platform must not be blank")
        if not isinstance(captured_at, str):
            raise ValueError("captured_at must be ISO 8601")
        try:
            parsed_time = datetime.fromisoformat(captured_at)
        except ValueError as exc:
            raise ValueError("captured_at must be ISO 8601") from exc
        if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
            raise ValueError("captured_at must include a UTC offset")
        canonical = canonical_url(url)
        normalized = normalize_content(content)
        if not normalized:
            raise ValueError("captured content is empty after normalization")
        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        page_key = self._page_key(platform, canonical)
        snapshot_id = f"{timestamp_slug(captured_at)}-{content_hash[:12]}"

        for attempt in range(self.max_index_retries):
            index_key = self._index_key(page_key)
            index, index_etag = self._get_json(index_key)
            previous = None
            if index is not None:
                previous_id = index.get("latest_snapshot_id")
                if not isinstance(previous_id, str) or not previous_id:
                    raise ValueError("S3 page index has no valid latest_snapshot_id")
                previous, _previous_etag = self._get_json(self._record_key(page_key, previous_id))
                if previous is None:
                    raise ValueError("S3 page index references a missing snapshot")
                previous_time = datetime.fromisoformat(str(previous.get("captured_at", "")))
                if previous_time.tzinfo is None or previous_time.utcoffset() is None:
                    raise ValueError("S3 latest snapshot has an invalid captured_at")
                if previous.get("snapshot_id") == snapshot_id and previous.get("content_hash") == content_hash:
                    return self._metadata(previous, page_key, previous.get("change_status") == "changed")
                if parsed_time <= previous_time:
                    raise ValueError("captured_at must advance beyond the latest S3 snapshot")

            previous_id = previous.get("snapshot_id") if previous else None
            if previous is None:
                change_status = "first_seen"
                diff_summary = "First captured snapshot; no historical baseline is available."
                diff_text = None
            elif previous.get("content_hash") == content_hash:
                change_status = "unchanged"
                diff_summary = "No normalized page-text change from the previous snapshot."
                diff_text = None
            else:
                change_status = "changed"
                diff_summary, diff_text = diff_details(str(previous.get("content", "")), normalized)

            record = {
                "schema_version": SNAPSHOT_VERSION,
                "snapshot_id": snapshot_id,
                "platform": platform,
                "url": canonical,
                "captured_at": captured_at,
                "content_hash": content_hash,
                "previous_snapshot_id": previous_id,
                "change_status": change_status,
                "diff_summary": diff_summary,
                "content": normalized,
            }
            record_bytes = (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            try:
                self._put(self._record_key(page_key, snapshot_id), record_bytes, "application/json", create_only=True)
            except BaseException as exc:
                if _error_code(exc) not in PRECONDITION_CODES:
                    raise
                existing, _existing_etag = self._get_json(self._record_key(page_key, snapshot_id))
                if existing != record:
                    raise ValueError("S3 snapshot ID collision with different content") from exc
            if diff_text is not None:
                try:
                    self._put(
                        self._diff_key(page_key, snapshot_id),
                        diff_text.encode("utf-8"),
                        "text/plain; charset=utf-8",
                        create_only=True,
                    )
                except BaseException as exc:
                    if _error_code(exc) not in PRECONDITION_CODES:
                        raise

            new_index = {
                "schema_version": SNAPSHOT_VERSION,
                "storage_backend": self.backend_name,
                "platform": platform,
                "url": canonical,
                "latest_snapshot_id": snapshot_id,
                "latest_snapshot_ref": self._record_key(page_key, snapshot_id),
                "updated_at": captured_at,
            }
            try:
                self._put(
                    index_key,
                    (json.dumps(new_index, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
                    "application/json",
                    etag=index_etag,
                )
            except BaseException as exc:
                if _error_code(exc) in PRECONDITION_CODES and attempt + 1 < self.max_index_retries:
                    continue
                if _error_code(exc) in PRECONDITION_CODES:
                    raise ValueError("S3 page index changed concurrently; retry capture") from exc
                raise
            return self._metadata(record, page_key, diff_text is not None)

        raise ValueError("S3 page index changed concurrently; retry capture")

    def audit(self) -> dict:
        """Verify reachable S3 snapshot chains, diffs, hashes, refs, and encryption metadata."""
        keys = self._list_keys()
        errors: list[str] = []
        index_keys = [key for key in keys if key.endswith("/index.json")]
        snapshot_keys = {key for key in keys if "/snapshots/" in key and key.endswith(".json")}
        diff_keys = {key for key in keys if "/diffs/" in key and key.endswith(".diff.txt")}
        referenced_snapshots: set[str] = set()
        referenced_diffs: set[str] = set()

        for key in keys:
            try:
                metadata = self.client.head_object(Bucket=self.bucket, Key=key)
                if metadata.get("ServerSideEncryption") != "AES256":
                    errors.append(f"object is not AES256 server-side encrypted: {key}")
            except BaseException as exc:
                errors.append(f"cannot inspect object metadata: {key}: {_error_code(exc) or type(exc).__name__}")

        for index_key in index_keys:
            relative = index_key[len(self.prefix) + 1 :] if self.prefix else index_key
            parts = relative.split("/")
            if len(parts) != 3 or parts[0] != "pages" or parts[2] != "index.json":
                errors.append(f"invalid page index key: {index_key}")
                continue
            page_key = parts[1]
            try:
                index, _etag = self._get_json(index_key)
            except (ValueError, json.JSONDecodeError) as exc:
                errors.append(f"invalid page index {index_key}: {exc}")
                continue
            if index is None:
                errors.append(f"missing page index: {index_key}")
                continue
            platform = index.get("platform")
            url = index.get("url")
            latest_id = index.get("latest_snapshot_id")
            if not all(isinstance(value, str) and value for value in (platform, url, latest_id)):
                errors.append(f"page index has incomplete identity: {index_key}")
                continue
            try:
                canonical = canonical_url(url)
            except ValueError as exc:
                errors.append(f"page index has invalid URL {index_key}: {exc}")
                continue
            if self._page_key(platform, canonical) != page_key:
                errors.append(f"page index key does not match platform and URL: {index_key}")

            chain: list[dict] = []
            seen_ids: set[str] = set()
            current_id = latest_id
            while current_id is not None:
                if current_id in seen_ids:
                    errors.append(f"snapshot predecessor cycle for page {page_key}: {current_id}")
                    break
                seen_ids.add(current_id)
                record_key = self._record_key(page_key, current_id)
                referenced_snapshots.add(record_key)
                try:
                    record, _record_etag = self._get_json(record_key)
                except (ValueError, json.JSONDecodeError) as exc:
                    errors.append(f"invalid snapshot {record_key}: {exc}")
                    break
                if record is None:
                    errors.append(f"missing snapshot referenced by index or chain: {record_key}")
                    break
                chain.append(record)
                previous_id = record.get("previous_snapshot_id")
                if previous_id is not None and not isinstance(previous_id, str):
                    errors.append(f"invalid previous_snapshot_id: {record_key}")
                    break
                current_id = previous_id

            chronological = list(reversed(chain))
            previous = None
            previous_time = None
            for record in chronological:
                snapshot_id = record.get("snapshot_id")
                record_key = self._record_key(page_key, str(snapshot_id))
                if record.get("schema_version") != SNAPSHOT_VERSION:
                    errors.append(f"unsupported snapshot schema: {record_key}")
                if not isinstance(snapshot_id, str) or record_key not in snapshot_keys:
                    errors.append(f"snapshot ID or object key mismatch: {record_key}")
                if record.get("platform") != platform or record.get("url") != canonical:
                    errors.append(f"snapshot identity differs from page index: {record_key}")
                normalized = normalize_content(str(record.get("content", "")))
                if not normalized or normalized != record.get("content"):
                    errors.append(f"snapshot content is empty or not normalized: {record_key}")
                expected_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                if record.get("content_hash") != expected_hash:
                    errors.append(f"snapshot content hash mismatch: {record_key}")
                try:
                    captured = datetime.fromisoformat(str(record.get("captured_at", "")))
                    if captured.tzinfo is None or captured.utcoffset() is None:
                        raise ValueError
                except ValueError:
                    errors.append(f"snapshot captured_at is invalid: {record_key}")
                    captured = None
                if captured is not None and previous_time is not None and captured <= previous_time:
                    errors.append(f"snapshot chain is not chronological: {record_key}")

                status = record.get("change_status")
                has_previous = previous is not None
                if not has_previous:
                    if status != "first_seen" or record.get("previous_snapshot_id") is not None:
                        errors.append(f"first snapshot semantics are invalid: {record_key}")
                else:
                    same_hash = record.get("content_hash") == previous.get("content_hash")
                    expected_status = "unchanged" if same_hash else "changed"
                    if status != expected_status or record.get("previous_snapshot_id") != previous.get("snapshot_id"):
                        errors.append(f"snapshot predecessor or change status is invalid: {record_key}")
                    diff_key = self._diff_key(page_key, str(snapshot_id))
                    if expected_status == "changed":
                        referenced_diffs.add(diff_key)
                        if diff_key not in diff_keys:
                            errors.append(f"changed snapshot is missing its diff: {diff_key}")
                        else:
                            response = self.client.get_object(Bucket=self.bucket, Key=diff_key)
                            body = response["Body"]
                            raw = body.read() if hasattr(body, "read") else body
                            expected_summary, expected_diff = diff_details(previous["content"], record["content"])
                            if bytes(raw).decode("utf-8") != expected_diff:
                                errors.append(f"snapshot diff content mismatch: {diff_key}")
                            if record.get("diff_summary") != expected_summary:
                                errors.append(f"snapshot diff summary mismatch: {record_key}")
                    elif diff_key in diff_keys:
                        errors.append(f"unchanged snapshot unexpectedly has a diff: {diff_key}")
                previous = record
                previous_time = captured

            expected_latest_ref = self._record_key(page_key, latest_id)
            if index.get("latest_snapshot_ref") != expected_latest_ref:
                errors.append(f"page index latest_snapshot_ref mismatch: {index_key}")

        for key in sorted(snapshot_keys - referenced_snapshots):
            errors.append(f"unreferenced snapshot object: {key}")
        for key in sorted(diff_keys - referenced_diffs):
            errors.append(f"unreferenced diff object: {key}")
        if snapshot_keys and not index_keys:
            errors.append("snapshot objects exist without any page index")
        return {
            "valid": not errors,
            "storage_backend": self.backend_name,
            "store": f"s3://{self.bucket}/{self.prefix}".rstrip("/"),
            "page_count": len(index_keys),
            "snapshot_count": len(snapshot_keys),
            "diff_count": len(diff_keys),
            "errors": errors,
        }
