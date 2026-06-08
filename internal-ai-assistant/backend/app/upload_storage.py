from pathlib import Path

from fastapi import HTTPException, UploadFile

from .config import MAX_UPLOAD_BYTES, MAX_UPLOAD_MB, UPLOAD_DIR
from .document_utils import safe_filename
from .routers.deps import new_id


def save_upload(file: UploadFile, prefix: str) -> tuple[str, Path, str]:
    filename = safe_filename(file.filename or "attachment")
    doc_id = new_id()
    storage_path = UPLOAD_DIR / f"{prefix}_{doc_id}_{filename}"
    total = 0
    try:
        with storage_path.open("wb") as f:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail=f"文件不能超过 {MAX_UPLOAD_MB}MB")
                f.write(chunk)
    except Exception:
        storage_path.unlink(missing_ok=True)
        raise
    return doc_id, storage_path, filename
