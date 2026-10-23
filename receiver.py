import asyncio
import io
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import qrcode
import qrcode.image.svg
import uvicorn

from services.config import (
    BASE_DIR,
    DEVICE_ID,
    DEVICE_NAME,
    DEVICE_TYPE,
    MAX_FILE_SIZE,
    PORT,
    SAVE_DIR,
)
from services.device_service import (
    approve_pairing_request,
    create_pairing_request,
    get_current_device_info,
    get_pairing_request_status,
    list_devices,
    list_pending_pairing_requests,
    refresh_pairing_credentials,
    register_discovered_device,
    reject_pairing_request,
    revoke_pairing,
)
from services.discovery_service import get_discovery_status, start_discovery, stop_discovery
from services.transfer_service import (
    get_file_response,
    get_pending_transfers_for,
    list_received_files,
    refresh_registry,
    save_upload_stream,
    stage_outgoing_transfer,
    update_transfer_status,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: start mDNS discovery in background thread
    start_discovery()
    refresh_registry()
    yield
    # Shutdown: cleanly stop discovery
    stop_discovery()


app = FastAPI(
    title="SkDrop",
    description="AirDrop-inspired local network file sharing",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for local network access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static folder
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# Pydantic schemas for request bodies
class PairingRequestBody(BaseModel):
    requester_id: str
    requester_name: str
    requester_type: str = "mobile"
    pin: Optional[str] = None
    token: Optional[str] = None


class DiscoverManualBody(BaseModel):
    ip: str
    port: int = 8000
    name: Optional[str] = None


class StageTransferBody(BaseModel):
    file_id: str
    target_device_id: str
    sender_name: str = "Laptop"


class TransferResponseBody(BaseModel):
    status: str  # accepted / rejected / completed


# Routes


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the SkDrop web app."""
    index_file = BASE_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>SkDrop</h1><p>index.html not found</p>", status_code=404)


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "app": "SkDrop",
        "version": "1.0.0",
        "device": get_current_device_info(),
        "discovery": get_discovery_status(),
        "max_file_size": MAX_FILE_SIZE,
    }


@app.get("/api/device")
async def get_device():
    """Return local device identity and pairing credentials."""
    return get_current_device_info()


@app.get("/api/pair/qr.svg")
async def get_pairing_qr_svg():
    """Generate and return an SVG QR code for instant mobile pairing."""
    creds = refresh_pairing_credentials()
    factory = qrcode.image.svg.SvgPathImage
    img = qrcode.make(creds["qr_url"], image_factory=factory)
    buf = io.BytesIO()
    img.save(buf)
    return Response(content=buf.getvalue(), media_type="image/svg+xml")


@app.get("/api/devices")
async def get_devices():
    """List discovered and paired devices on the local network."""
    return {
        "self": get_current_device_info(),
        "devices": list_devices(),
        "discovery": get_discovery_status(),
    }


@app.post("/api/devices/discover")
async def discover_manual(body: DiscoverManualBody):
    """Manually probe a device by IP address."""
    clean_ip = body.ip.strip()
    # Basic validation
    if not clean_ip:
        raise HTTPException(status_code=400, detail="IP address is required")

    peer_id = f"manual_{clean_ip.replace('.', '_')}"
    peer_name = body.name or f"Device ({clean_ip})"
    register_discovered_device(peer_id, peer_name, "unknown", clean_ip, body.port)

    return {
        "status": "registered",
        "device_id": peer_id,
        "device_name": peer_name,
        "ip": clean_ip,
        "port": body.port,
    }


@app.post("/api/pair/request")
async def request_pairing(body: PairingRequestBody, request: Request):
    """Initiate a pairing request from another device."""
    client_ip = request.client.host if request.client else "unknown"
    req = create_pairing_request(
        requester_id=body.requester_id,
        requester_name=body.requester_name,
        requester_type=body.requester_type,
        requester_ip=client_ip,
        provided_pin=body.pin,
        provided_token=body.token,
    )
    return req


@app.get("/api/pair/requests")
async def get_pairing_requests():
    """List pending pairing requests waiting for receiver approval."""
    return {"requests": list_pending_pairing_requests()}


@app.get("/api/pair/request/{request_id}")
async def check_pairing_request(request_id: str):
    """Poll status of a pairing request."""
    return get_pairing_request_status(request_id)


@app.post("/api/pair/approve/{request_id}")
async def approve_pairing(request_id: str):
    """Receiver approves a pending pairing request."""
    return approve_pairing_request(request_id)


@app.post("/api/pair/reject/{request_id}")
async def reject_pairing(request_id: str):
    """Receiver declines a pending pairing request."""
    return reject_pairing_request(request_id)


@app.post("/api/pair/revoke/{device_id}")
async def revoke_device_pairing(device_id: str):
    """Revoke pairing for a specific device."""
    success = revoke_pairing(device_id)
    return {"device_id": device_id, "revoked": success}


# File Upload & Transfer Endpoints


@app.post("/api/upload")
async def api_upload_file(file: UploadFile = File(...)):
    """API endpoint for chunked streaming upload with size validation."""
    file_info = await save_upload_stream(file)
    return {"success": True, "file": file_info}


@app.post("/upload", response_class=HTMLResponse)
async def legacy_upload(file: UploadFile = File(...)):
    """Preserve backwards-compatible form upload with HTML confirmation."""
    file_info = await save_upload_stream(file)
    size_mb = file_info["size"] / (1024 * 1024)
    return f"""
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>SkDrop — Upload Complete</title>
        <style>
          body {{ font-family: -apple-system, system-ui, sans-serif; text-align: center; margin-top: 60px; background: #0b1020; color: #f3f6ff; }}
          .box {{ max-width: 420px; margin: 0 auto; padding: 30px; background: #141b2d; border-radius: 16px; border: 1px solid #28334a; }}
          a {{ color: #70a5ff; text-decoration: none; font-weight: 600; display: inline-block; margin-top: 15px; }}
        </style>
      </head>
      <body>
        <div class="box">
          <h2>File received successfully!</h2>
          <p>Saved as: <strong>{file_info['name']}</strong></p>
          <p>Size: {size_mb:.2f} MB</p>
          <a href="/">← Back to SkDrop</a>
        </div>
      </body>
    </html>
    """


@app.get("/api/files")
async def get_files():
    """List all received files."""
    return {"files": list_received_files()}


@app.get("/api/download/{identifier}")
async def download_file(identifier: str):
    """Download a received file by server-generated file_id or filename."""
    # First attempt to resolve by server-generated file_id
    try:
        return get_file_response(identifier)
    except HTTPException as e:
        if e.status_code != 404:
            raise

    # Backwards-compatibility fallback: check if identifier matches a direct filename in registry
    refresh_registry()
    for file_info in list_received_files():
        if file_info["name"] == identifier or file_info["filename_on_disk"] == identifier:
            return get_file_response(file_info["id"])

    raise HTTPException(status_code=404, detail="File not found")


# Two-way Transfer (Laptop -> Phone staging and notification)


@app.post("/api/transfer/send")
async def send_transfer_offer(body: StageTransferBody):
    """Stage an outgoing file transfer to a paired recipient."""
    transfer = stage_outgoing_transfer(
        file_id=body.file_id,
        target_device_id=body.target_device_id,
        sender_name=body.sender_name,
    )
    return {"success": True, "transfer": transfer}


@app.get("/api/transfer/pending/{device_id}")
async def get_pending_transfers(device_id: str):
    """Check for pending transfer offers addressed to this device."""
    offers = get_pending_transfers_for(device_id)
    return {"transfers": offers}


@app.post("/api/transfer/respond/{transfer_id}")
async def respond_to_transfer(transfer_id: str, body: TransferResponseBody):
    """Recipient accepts or rejects a transfer offer."""
    updated = update_transfer_status(transfer_id, body.status)
    return {"success": True, "transfer": updated}


if __name__ == "__main__":
    uvicorn.run("receiver:app", host="0.0.0.0", port=PORT, reload=True)
