import json
import secrets
import time
import uuid
from typing import Dict, List, Optional
from fastapi import HTTPException

from .config import BASE_DIR, DEVICE_ID, DEVICE_NAME, DEVICE_TYPE, PORT, get_local_ip

PAIRED_STORE_FILE = BASE_DIR / ".paired_devices.json"

# In-memory pairing state
_paired_devices: Dict[str, dict] = {}
# Pending pairing requests waiting for receiver approval: request_id -> dict
_pending_pairing_requests: Dict[str, dict] = {}
# Discovered devices (via mDNS or manual IP lookup): device_id -> dict
_discovered_devices: Dict[str, dict] = {}

# Active short-lived pairing PIN & token
_current_pin: str = f"{secrets.randbelow(900000) + 100000}"
_current_token: str = secrets.token_urlsafe(16)
_pin_expiry: float = time.time() + 300  # 5 minutes


def load_paired_devices():
    """Load persisted paired devices from disk."""
    global _paired_devices
    if PAIRED_STORE_FILE.exists():
        try:
            data = json.loads(PAIRED_STORE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _paired_devices = data
        except Exception:
            _paired_devices = {}


def save_paired_devices():
    """Persist paired devices to disk."""
    try:
        PAIRED_STORE_FILE.write_text(json.dumps(_paired_devices, indent=2), encoding="utf-8")
    except Exception:
        pass


load_paired_devices()


def refresh_pairing_credentials() -> dict:
    """Generate or retrieve the active short-lived pairing credentials."""
    global _current_pin, _current_token, _pin_expiry
    now = time.time()
    if now > _pin_expiry:
        _current_pin = f"{secrets.randbelow(900000) + 100000}"
        _current_token = secrets.token_urlsafe(16)
        _pin_expiry = now + 300  # Refresh for 5 minutes

    local_ip = get_local_ip()
    qr_url = f"http://{local_ip}:{PORT}/?pair=1&pin={_current_pin}&token={_current_token}"

    return {
        "pin": _current_pin,
        "token": _current_token,
        "expires_in": max(0, int(_pin_expiry - now)),
        "qr_url": qr_url,
        "local_ip": local_ip,
        "port": PORT,
    }


def get_current_device_info() -> dict:
    """Return local device identity and status."""
    creds = refresh_pairing_credentials()
    return {
        "device_id": DEVICE_ID,
        "device_name": DEVICE_NAME,
        "device_type": DEVICE_TYPE,
        "ip": creds["local_ip"],
        "port": PORT,
        "pin": creds["pin"],
        "token": creds["token"],
        "qr_url": creds["qr_url"],
        "expires_in": creds["expires_in"],
        "is_online": True,
    }


def create_pairing_request(
    requester_id: str,
    requester_name: str,
    requester_type: str,
    requester_ip: str,
    provided_pin: Optional[str] = None,
    provided_token: Optional[str] = None,
) -> dict:
    """Register an incoming pairing request for receiver approval."""
    global _current_pin, _current_token

    # Verify pin or token matches receiver's active credentials
    pin_matched = bool(provided_pin and provided_pin.strip() == _current_pin)
    token_matched = bool(provided_token and provided_token.strip() == _current_token)

    if not (pin_matched or token_matched):
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired pairing PIN/token. Check credentials on receiver screen.",
        )

    # Expire old requests
    cleanup_old_requests()

    request_id = str(uuid.uuid4())
    req = {
        "request_id": request_id,
        "requester_id": requester_id,
        "requester_name": requester_name,
        "requester_type": requester_type,
        "requester_ip": requester_ip,
        "pin": _current_pin,
        "status": "pending",  # pending, approved, rejected
        "created_at": time.time(),
    }
    _pending_pairing_requests[request_id] = req
    return req


def list_pending_pairing_requests() -> List[dict]:
    """Return all pending pairing requests awaiting receiver approval."""
    cleanup_old_requests()
    return [r for r in _pending_pairing_requests.values() if r["status"] == "pending"]


def get_pairing_request_status(request_id: str) -> dict:
    """Check the status of a specific pairing request."""
    if request_id not in _pending_pairing_requests:
        raise HTTPException(status_code=404, detail="Pairing request not found or expired")
    return _pending_pairing_requests[request_id]


def approve_pairing_request(request_id: str) -> dict:
    """Receiver approves a pairing request."""
    if request_id not in _pending_pairing_requests:
        raise HTTPException(status_code=404, detail="Pairing request not found")

    req = _pending_pairing_requests[request_id]
    auth_token = secrets.token_hex(24)

    paired_record = {
        "device_id": req["requester_id"],
        "device_name": req["requester_name"],
        "device_type": req["requester_type"],
        "ip": req["requester_ip"],
        "paired_at": time.time(),
        "auth_token": auth_token,
        "status": "paired",
    }

    _paired_devices[req["requester_id"]] = paired_record
    save_paired_devices()

    req["status"] = "approved"
    req["auth_token"] = auth_token

    # Also register in discovered devices
    _discovered_devices[req["requester_id"]] = {
        "device_id": req["requester_id"],
        "device_name": req["requester_name"],
        "device_type": req["requester_type"],
        "ip": req["requester_ip"],
        "port": PORT,
        "last_seen": time.time(),
        "status": "paired",
    }

    return req


def reject_pairing_request(request_id: str) -> dict:
    """Receiver declines a pairing request."""
    if request_id not in _pending_pairing_requests:
        raise HTTPException(status_code=404, detail="Pairing request not found")

    req = _pending_pairing_requests[request_id]
    req["status"] = "rejected"
    return req


def revoke_pairing(device_id: str) -> bool:
    """Revoke an existing paired device."""
    if device_id in _paired_devices:
        del _paired_devices[device_id]
        save_paired_devices()
        if device_id in _discovered_devices:
            _discovered_devices[device_id]["status"] = "discovered"
        return True
    return False


def is_paired(device_id: str) -> bool:
    """Check if device is paired."""
    return device_id in _paired_devices


def register_discovered_device(device_id: str, device_name: str, device_type: str, ip: str, port: int = 8000):
    """Update discovered devices registry (e.g. from mDNS, UDP, or ping)."""
    if device_id == DEVICE_ID:
        return  # Don't list self

    status = "paired" if is_paired(device_id) else "discovered"
    _discovered_devices[device_id] = {
        "device_id": device_id,
        "device_name": device_name,
        "device_type": device_type,
        "ip": ip,
        "port": port,
        "last_seen": time.time(),
        "status": status,
    }


def list_devices() -> List[dict]:
    """List all known devices with their current state (discovered, paired, reachable, offline)."""
    now = time.time()
    devices = []

    # Include all paired devices
    for dev_id, pdev in _paired_devices.items():
        # Check last seen
        last_seen = pdev.get("last_seen", pdev.get("paired_at", now))
        is_reachable = (now - last_seen) < 180  # Reachable within 3 minutes
        devices.append({
            "device_id": dev_id,
            "device_name": pdev.get("device_name", "Unknown Device"),
            "device_type": pdev.get("device_type", "unknown"),
            "ip": pdev.get("ip", ""),
            "status": "paired",
            "connection_state": "reachable" if is_reachable else "offline",
            "paired_at": pdev.get("paired_at"),
        })

    # Include discovered but unpaired devices
    for dev_id, ddev in _discovered_devices.items():
        if dev_id not in _paired_devices:
            last_seen = ddev.get("last_seen", now)
            is_reachable = (now - last_seen) < 120
            devices.append({
                "device_id": dev_id,
                "device_name": ddev.get("device_name", "Unknown Device"),
                "device_type": ddev.get("device_type", "unknown"),
                "ip": ddev.get("ip", ""),
                "status": "discovered",
                "connection_state": "reachable" if is_reachable else "offline",
                "last_seen": last_seen,
            })

    return devices


def cleanup_old_requests():
    """Remove expired requests older than 5 minutes."""
    now = time.time()
    for rid, req in list(_pending_pairing_requests.items()):
        if now - req.get("created_at", 0) > 300:
            del _pending_pairing_requests[rid]
