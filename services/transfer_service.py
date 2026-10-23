import os
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse

from .config import CHUNK_SIZE, MAX_FILE_SIZE, SAVE_DIR, TEMP_DIR

# Registry mapping file_id -> metadata
_files_registry: Dict[str, dict] = {}
# Pending outgoing transfers: transfer_id -> transfer_info
_pending_transfers: Dict[str, dict] = {}


def sanitize_filename(filename: Optional[str]) -> str:
    """Sanitize filename to prevent path traversal and invalid filesystem characters."""
    if not filename:
        return "upload.bin"

    # Replace backslashes with forward slashes and take basename
    clean = filename.replace("\\", "/").split("/")[-1].strip()

    # Strip null bytes and control chars
    clean = re.sub(r"[\x00-\x1f\x7f]", "", clean)

    # Strip Windows reserved chars: < > : " / \ | ? *
    clean = re.sub(r'[<>:"/\\|?*]', "", clean)

    # Strip leading/trailing dots and spaces (Windows doesn't support trailing dots/spaces)
    clean = clean.strip(". ")

    # Limit filename length
    if len(clean) > 200:
        stem, ext = os.path.splitext(clean)
        clean = stem[:190] + ext

    if not clean or clean in {".", ".."}:
        clean = "upload.bin"

    return clean


def get_unique_destination(target_dir: Path, filename: str) -> Path:
    """Return a non-colliding Path in target_dir by appending (1), (2), etc."""
    base_stem = Path(filename).stem
    suffix = Path(filename).suffix
    destination = target_dir / filename

    counter = 1
    while destination.exists():
        destination = target_dir / f"{base_stem} ({counter}){suffix}"
        counter += 1

    return destination


def refresh_registry() -> Dict[str, dict]:
    """Scan SAVE_DIR and update registry with all valid files."""
    global _files_registry

    # Keep existing IDs for files still on disk
    disk_files = {f.name: f for f in SAVE_DIR.iterdir() if f.is_file()}

    # Remove deleted files from registry
    to_delete = [
        fid for fid, info in _files_registry.items()
        if info["filename_on_disk"] not in disk_files
    ]
    for fid in to_delete:
        del _files_registry[fid]

    # Register any untracked disk files
    registered_disk_names = {info["filename_on_disk"] for info in _files_registry.values()}
    for name, path in disk_files.items():
        if name not in registered_disk_names:
            file_id = str(uuid.uuid4())
            try:
                stat = path.stat()
                size = stat.st_size
                mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
            except Exception:
                size = 0
                mtime = datetime.now(tz=timezone.utc).isoformat()

            _files_registry[file_id] = {
                "id": file_id,
                "name": name,
                "filename_on_disk": name,
                "size": size,
                "timestamp": mtime,
            }

    return _files_registry


async def save_upload_stream(file: UploadFile) -> dict:
    """Stream upload into TEMP_DIR, validate size, then atomically move to SAVE_DIR."""
    clean_name = sanitize_filename(file.filename)
    temp_name = f"upload_{uuid.uuid4().hex}_{clean_name}"
    temp_path = TEMP_DIR / temp_name

    total_size = 0

    try:
        with temp_path.open("wb") as out_file:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total_size += len(chunk)

                if total_size > MAX_FILE_SIZE:
                    out_file.close()
                    temp_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds maximum allowed size of {MAX_FILE_SIZE // (1024 * 1024)} MB",
                    )
                out_file.write(chunk)

        # File is fully written and within size limit, determine non-colliding destination
        final_dest = get_unique_destination(SAVE_DIR, clean_name)
        shutil.move(str(temp_path), str(final_dest))

        file_id = str(uuid.uuid4())
        file_info = {
            "id": file_id,
            "name": final_dest.name,
            "filename_on_disk": final_dest.name,
            "size": total_size,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }

        _files_registry[file_id] = file_info
        return file_info

    except HTTPException:
        temp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Failed to process upload: {str(exc)}")
    finally:
        await file.close()


def list_received_files() -> List[dict]:
    """Return all received files sorted by newest first."""
    refresh_registry()
    files = list(_files_registry.values())
    files.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return files


def get_file_response(file_id: str) -> FileResponse:
    """Safely resolve file by server-generated ID and return a FileResponse."""
    refresh_registry()

    if file_id not in _files_registry:
        raise HTTPException(status_code=404, detail="File ID not found")

    file_info = _files_registry[file_id]
    target_path = (SAVE_DIR / file_info["filename_on_disk"]).resolve()

    # Enforce path traversal prevention: ensure target is strictly inside SAVE_DIR
    if not str(target_path).startswith(str(SAVE_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Forbidden file access")

    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=404, detail="File no longer exists on disk")

    return FileResponse(
        path=str(target_path),
        filename=file_info["name"],
        media_type="application/octet-stream",
    )


# Outgoing file transfer staging (for laptop -> phone or laptop -> laptop)
def stage_outgoing_transfer(file_id: str, target_device_id: str, sender_name: str) -> dict:
    refresh_registry()
    if file_id not in _files_registry:
        raise HTTPException(status_code=404, detail="File ID not found")

    file_info = _files_registry[file_id]
    transfer_id = str(uuid.uuid4())
    transfer = {
        "transfer_id": transfer_id,
        "file_id": file_id,
        "name": file_info["name"],
        "size": file_info["size"],
        "sender_name": sender_name,
        "target_device_id": target_device_id,
        "status": "pending",  # pending, accepted, rejected, completed
        "created_at": time.time(),
    }
    _pending_transfers[transfer_id] = transfer
    return transfer


def get_pending_transfers_for(target_device_id: str) -> List[dict]:
    """Retrieve pending transfers targeted to a specific device."""
    now = time.time()
    # Expire after 10 minutes
    valid = []
    for tid, t in list(_pending_transfers.items()):
        if now - t.get("created_at", 0) > 600:
            del _pending_transfers[tid]
            continue
        if t.get("target_device_id") == target_device_id and t.get("status") == "pending":
            valid.append(t)
    return valid


def update_transfer_status(transfer_id: str, status: str) -> dict:
    if transfer_id not in _pending_transfers:
        raise HTTPException(status_code=404, detail="Transfer not found")
    _pending_transfers[transfer_id]["status"] = status
    return _pending_transfers[transfer_id]
