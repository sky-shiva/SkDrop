import pytest
from fastapi.testclient import TestClient
from receiver import app

client = TestClient(app)


def test_pairing_flow_with_approval():
    # 1. Get host pairing PIN
    dev_res = client.get("/api/device")
    assert dev_res.status_code == 200
    host_info = dev_res.json()
    valid_pin = host_info["pin"]

    # 2. Peer submits pairing request with valid PIN
    peer_payload = {
        "requester_id": "test-phone-123",
        "requester_name": "Test Pixel 8",
        "requester_type": "mobile",
        "pin": valid_pin,
    }
    req_res = client.post("/api/pair/request", json=peer_payload)
    assert req_res.status_code == 200
    req_data = req_res.json()
    assert req_data["status"] == "pending"
    request_id = req_data["request_id"]

    # 3. Check pending requests on receiver
    pending_res = client.get("/api/pair/requests")
    assert pending_res.status_code == 200
    requests = pending_res.json()["requests"]
    assert any(r["request_id"] == request_id for r in requests)

    # 4. Receiver approves the pairing request
    approve_res = client.post(f"/api/pair/approve/{request_id}")
    assert approve_res.status_code == 200
    assert approve_res.json()["status"] == "approved"
    assert "auth_token" in approve_res.json()

    # 5. Peer polls request status and finds it approved
    status_res = client.get(f"/api/pair/request/{request_id}")
    assert status_res.status_code == 200
    assert status_res.json()["status"] == "approved"

    # 6. Check devices list shows paired
    devices_res = client.get("/api/devices")
    devices = devices_res.json()["devices"]
    assert any(d["device_id"] == "test-phone-123" and d["status"] == "paired" for d in devices)

    # 7. Receiver revokes pairing
    revoke_res = client.post("/api/pair/revoke/test-phone-123")
    assert revoke_res.status_code == 200
    assert revoke_res.json()["revoked"] is True


def test_pairing_with_invalid_pin():
    peer_payload = {
        "requester_id": "test-rogue-device",
        "requester_name": "Rogue Device",
        "requester_type": "mobile",
        "pin": "000000_invalid",
    }
    response = client.post("/api/pair/request", json=peer_payload)
    assert response.status_code == 400
    assert "Invalid or expired" in response.json()["detail"]


def test_pairing_qr_svg():
    response = client.get("/api/pair/qr.svg")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in response.content


def test_pairing_with_token():

    dev_res = client.get("/api/device")
    valid_token = dev_res.json()["token"]

    peer_payload = {
        "requester_id": "test-qr-device",
        "requester_name": "Test QR Phone",
        "requester_type": "mobile",
        "token": valid_token,
    }
    response = client.post("/api/pair/request", json=peer_payload)
    assert response.status_code == 200
    req_data = response.json()
    assert req_data["status"] == "pending"

    # Reject request test
    reject_res = client.post(f"/api/pair/reject/{req_data['request_id']}")
    assert reject_res.status_code == 200
    assert reject_res.json()["status"] == "rejected"
