import os
import socket
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SAVE_DIR = BASE_DIR / "received_files"
TEMP_DIR = BASE_DIR / "temp"

SAVE_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Configuration defaults
DEFAULT_MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", str(DEFAULT_MAX_FILE_SIZE)))
CHUNK_SIZE = 1024 * 1024  # 1 MB
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")
ENABLE_MDNS = os.getenv("ENABLE_MDNS", "true").lower() in ("1", "true", "yes")

def get_local_ip() -> str:
    """Determine the primary local IPv4 address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connect to a public DNS IP without sending packets
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

def get_or_create_device_id() -> str:
    """Persist a unique device ID across runs."""
    id_file = BASE_DIR / ".device_id"
    if id_file.exists():
        try:
            device_id = id_file.read_text(encoding="utf-8").strip()
            if device_id:
                return device_id
        except Exception:
            pass
    device_id = str(uuid.uuid4())
    try:
        id_file.write_text(device_id, encoding="utf-8")
    except Exception:
        pass
    return device_id

DEVICE_ID = get_or_create_device_id()
DEVICE_NAME = os.getenv("DEVICE_NAME") or socket.gethostname() or "SkDrop-Host"
DEVICE_TYPE = "desktop"  # Receiver runs on desktop/server by default
