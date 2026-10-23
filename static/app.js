// SkDrop Frontend Application
(function () {
  "use strict";

  // Client device identity stored in localStorage
  function getClientIdentity() {
    let id = localStorage.getItem("skdrop_client_id");
    if (!id) {
      id = "client_" + Math.random().toString(36).substring(2, 10);
      localStorage.setItem("skdrop_client_id", id);
    }
    const isMobile = /Android|iPhone|iPad|iPod|webOS/i.test(navigator.userAgent);
    const clientType = isMobile ? "mobile" : "desktop";
    let defaultName = isMobile ? "Phone (Android)" : "Computer (Web)";
    if (/Android/i.test(navigator.userAgent)) defaultName = "Android Phone";
    else if (/iPhone/i.test(navigator.userAgent)) defaultName = "iPhone";
    else if (/Windows/i.test(navigator.userAgent)) defaultName = "Windows PC";
    else if (/Macintosh/i.test(navigator.userAgent)) defaultName = "Mac";

    let name = localStorage.getItem("skdrop_client_name") || defaultName;
    return { id, name, type: clientType };
  }

  const clientInfo = getClientIdentity();
  let hostInfo = null;
  let selectedTargetDevice = null;
  let isUploading = false;

  // DOM Elements
  const hostNameEl = document.getElementById("hostName");
  const hostIpEl = document.getElementById("hostIp");
  const hostStatusDot = document.getElementById("hostStatusDot");
  const discoveryBadge = document.getElementById("discoveryBadge");
  const devicesGrid = document.getElementById("devicesGrid");
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");
  const queueList = document.getElementById("queueList");
  const fileList = document.getElementById("fileList");
  const refreshFilesBtn = document.getElementById("refreshFilesBtn");
  const openPairModalBtn = document.getElementById("openPairModalBtn");
  const closePairModalBtn = document.getElementById("closePairModalBtn");
  const pairModal = document.getElementById("pairModal");
  const qrImage = document.getElementById("qrImage");
  const currentPinEl = document.getElementById("currentPin");
  const directLinkEl = document.getElementById("directLink");
  const targetIndicator = document.getElementById("targetIndicator");

  // Pair Request Approval Modal Elements
  const approvalModal = document.getElementById("approvalModal");
  const approvalDeviceName = document.getElementById("approvalDeviceName");
  const approvalPin = document.getElementById("approvalPin");
  const approveBtn = document.getElementById("approveBtn");
  const declineBtn = document.getElementById("declineBtn");
  let activeRequestId = null;

  // Incoming File Transfer Modal Elements
  const incomingFileModal = document.getElementById("incomingFileModal");
  const incomingSenderName = document.getElementById("incomingSenderName");
  const incomingFileName = document.getElementById("incomingFileName");
  const incomingFileSize = document.getElementById("incomingFileSize");
  const acceptFileBtn = document.getElementById("acceptFileBtn");
  const declineFileBtn = document.getElementById("declineFileBtn");
  let activeTransfer = null;

  // Helper formatting
  function formatBytes(bytes) {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  }

  // Fetch host info
  async function loadHostInfo() {
    try {
      const res = await fetch("/api/device");
      if (!res.ok) throw new Error("Offline");
      hostInfo = await res.json();
      hostNameEl.textContent = hostInfo.device_name;
      hostIpEl.textContent = `${hostInfo.ip}:${hostInfo.port}`;
      hostStatusDot.classList.remove("offline");
      currentPinEl.textContent = hostInfo.pin;
      directLinkEl.href = hostInfo.qr_url;
      directLinkEl.textContent = hostInfo.qr_url;
      qrImage.src = "/api/pair/qr.svg?t=" + Date.now();
    } catch (err) {
      hostStatusDot.classList.add("offline");
      hostIpEl.textContent = "Offline or unreachable";
    }
  }

  // Fetch and render devices
  async function loadDevices() {
    try {
      const res = await fetch("/api/devices");
      if (!res.ok) return;
      const data = await res.json();

      // Update discovery status
      if (data.discovery) {
        if (data.discovery.active) {
          discoveryBadge.className = "badge badge-green";
          discoveryBadge.textContent = "mDNS Active";
        } else {
          discoveryBadge.className = "badge badge-muted";
          discoveryBadge.textContent = "Manual / QR Mode";
        }
      }

      const devices = data.devices || [];
      devicesGrid.innerHTML = "";

      if (devices.length === 0) {
        devicesGrid.innerHTML = `
          <div class="empty-state" style="grid-column: 1 / -1;">
            <p>No nearby devices paired or discovered yet.</p>
            <p style="margin-top: 6px; font-size: 13px;">Open SkDrop on your phone or tap <strong>Pair New Device</strong> to connect.</p>
          </div>
        `;
        return;
      }

      devices.forEach((dev) => {
        const isPaired = dev.status === "paired";
        const icon = dev.device_type === "mobile" ? "📱" : "💻";
        const isSelected = selectedTargetDevice && selectedTargetDevice.device_id === dev.device_id;

        const card = document.createElement("div");
        card.className = "device-card" + (isSelected ? " selected" : "");
        card.innerHTML = `
          <div class="device-card-top">
            <div class="device-avatar">${icon}</div>
            <div class="device-meta">
              <div class="device-title">${escapeHtml(dev.device_name)}</div>
              <div class="device-sub">${escapeHtml(dev.ip || "LAN")} · ${dev.connection_state}</div>
            </div>
            <span class="badge ${isPaired ? "badge-green" : "badge-blue"}">
              ${isPaired ? "Paired" : "Discovered"}
            </span>
          </div>
          <div class="device-card-actions">
            ${
              isPaired
                ? `<button type="button" class="btn btn-sm btn-primary send-to-btn" data-id="${dev.device_id}">Send File</button>
                   <button type="button" class="btn btn-sm btn-danger unpair-btn" data-id="${dev.device_id}">Unpair</button>`
                : `<button type="button" class="btn btn-sm btn-primary pair-btn" data-id="${dev.device_id}">Pair</button>`
            }
          </div>
        `;

        // Event listeners for actions
        const sendBtn = card.querySelector(".send-to-btn");
        if (sendBtn) {
          sendBtn.addEventListener("click", () => {
            selectTargetDevice(dev);
            fileInput.click();
          });
        }

        const unpairBtn = card.querySelector(".unpair-btn");
        if (unpairBtn) {
          unpairBtn.addEventListener("click", async () => {
            if (confirm(`Unpair from ${dev.device_name}?`)) {
              await fetch(`/api/pair/revoke/${dev.device_id}`, { method: "POST" });
              if (selectedTargetDevice && selectedTargetDevice.device_id === dev.device_id) {
                selectTargetDevice(null);
              }
              loadDevices();
            }
          });
        }

        const pairBtn = card.querySelector(".pair-btn");
        if (pairBtn) {
          pairBtn.addEventListener("click", () => {
            openPairModal("code");
          });
        }

        devicesGrid.appendChild(card);
      });
    } catch (err) {
      console.error("Error loading devices:", err);
    }
  }

  function selectTargetDevice(dev) {
    selectedTargetDevice = dev;
    if (dev) {
      targetIndicator.textContent = `Target: ${dev.device_name} (Direct Transfer)`;
      targetIndicator.style.display = "inline-block";
    } else {
      targetIndicator.textContent = `Target: SkDrop Server (Default)`;
      targetIndicator.style.display = "none";
    }
  }

  // Load received files
  async function loadFiles() {
    try {
      const res = await fetch("/api/files");
      if (!res.ok) throw new Error("Failed to load files");
      const data = await res.json();
      const files = data.files || [];

      fileList.innerHTML = "";
      if (files.length === 0) {
        fileList.innerHTML = `<div class="empty-state">No received files yet. Transferred files will appear here.</div>`;
        return;
      }

      files.forEach((file) => {
        const item = document.createElement("div");
        item.className = "file-item";
        item.innerHTML = `
          <div class="file-item-left">
            <div class="file-icon">📄</div>
            <div class="file-details">
              <div class="file-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</div>
              <div class="file-meta">${formatBytes(file.size)}</div>
            </div>
          </div>
          <a class="btn btn-sm btn-primary" href="/api/download/${encodeURIComponent(file.id)}" download="${escapeHtml(file.name)}">
            Download
          </a>
        `;
        fileList.appendChild(item);
      });
    } catch (err) {
      fileList.innerHTML = `<div class="empty-state">Could not load files. Click refresh to retry.</div>`;
    }
  }

  // Check incoming pairing requests (Receiver approval)
  async function checkPairingRequests() {
    try {
      const res = await fetch("/api/pair/requests");
      if (!res.ok) return;
      const data = await res.json();
      const requests = data.requests || [];

      if (requests.length > 0 && !activeRequestId) {
        const req = requests[0];
        activeRequestId = req.request_id;
        approvalDeviceName.textContent = `${req.requester_name} (${req.requester_type})`;
        approvalPin.textContent = req.pin || "------";
        approvalModal.classList.add("active");
      }
    } catch (err) {}
  }

  // Approve pairing
  approveBtn.addEventListener("click", async () => {
    if (!activeRequestId) return;
    try {
      await fetch(`/api/pair/approve/${activeRequestId}`, { method: "POST" });
      approvalModal.classList.remove("active");
      activeRequestId = null;
      loadDevices();
    } catch (err) {
      alert("Failed to approve pairing");
    }
  });

  // Decline pairing
  declineBtn.addEventListener("click", async () => {
    if (!activeRequestId) return;
    try {
      await fetch(`/api/pair/reject/${activeRequestId}`, { method: "POST" });
      approvalModal.classList.remove("active");
      activeRequestId = null;
    } catch (err) {}
  });

  // Check incoming file offers (Laptop -> Phone direct transfer)
  async function checkIncomingTransfers() {
    try {
      const res = await fetch(`/api/transfer/pending/${clientInfo.id}`);
      if (!res.ok) return;
      const data = await res.json();
      const transfers = data.transfers || [];

      if (transfers.length > 0 && !activeTransfer) {
        const t = transfers[0];
        activeTransfer = t;
        incomingSenderName.textContent = t.sender_name || "Laptop";
        incomingFileName.textContent = t.name;
        incomingFileSize.textContent = formatBytes(t.size);
        incomingFileModal.classList.add("active");
      }
    } catch (err) {}
  }

  // Accept incoming transfer
  acceptFileBtn.addEventListener("click", async () => {
    if (!activeTransfer) return;
    const t = activeTransfer;
    incomingFileModal.classList.remove("active");
    activeTransfer = null;

    try {
      // Mark accepted
      await fetch(`/api/transfer/respond/${t.transfer_id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "accepted" }),
      });

      // Trigger browser download
      const a = document.createElement("a");
      a.href = `/api/download/${t.file_id}`;
      a.download = t.name;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch (err) {
      alert("Error receiving file: " + err);
    }
  });

  // Decline incoming transfer
  declineFileBtn.addEventListener("click", async () => {
    if (!activeTransfer) return;
    const t = activeTransfer;
    incomingFileModal.classList.remove("active");
    activeTransfer = null;
    try {
      await fetch(`/api/transfer/respond/${t.transfer_id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "rejected" }),
      });
    } catch (err) {}
  });

  // Multi-file Upload handler
  async function uploadFiles(files) {
    if (files.length === 0 || isUploading) return;
    isUploading = true;
    queueList.innerHTML = "";

    for (const file of files) {
      const queueItem = document.createElement("div");
      queueItem.className = "queue-card";
      queueItem.innerHTML = `
        <div class="queue-info">
          <span class="queue-filename" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</span>
          <span class="queue-status" style="color: var(--text-muted); font-size: 12px;">Waiting...</span>
        </div>
        <div class="progress-track">
          <div class="progress-fill"></div>
        </div>
      `;
      queueList.appendChild(queueItem);

      const statusEl = queueItem.querySelector(".queue-status");
      const progressFill = queueItem.querySelector(".progress-fill");

      if (file.size > 100 * 1024 * 1024) {
        statusEl.textContent = "Exceeds 100MB limit";
        statusEl.style.color = "var(--red)";
        progressFill.classList.add("error");
        progressFill.style.width = "100%";
        continue;
      }

      await new Promise((resolve) => {
        const formData = new FormData();
        formData.append("file", file);

        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/api/upload");

        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            const pct = Math.round((e.loaded / e.total) * 100);
            progressFill.style.width = pct + "%";
            statusEl.textContent = `Uploading ${pct}%`;
          }
        };

        xhr.onload = async () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            progressFill.style.width = "100%";
            progressFill.classList.add("success");
            statusEl.textContent = "Completed";
            statusEl.style.color = "var(--green)";

            try {
              const resData = JSON.parse(xhr.responseText);
              // If target device is selected, stage transfer to it
              if (selectedTargetDevice && resData.file && resData.file.id) {
                await fetch("/api/transfer/send", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                    file_id: resData.file.id,
                    target_device_id: selectedTargetDevice.device_id,
                    sender_name: clientInfo.name,
                  }),
                });
                statusEl.textContent = `Sent to ${selectedTargetDevice.device_name}`;
              }
            } catch (e) {}

            resolve();
          } else {
            progressFill.classList.add("error");
            progressFill.style.width = "100%";
            let errText = "Upload failed";
            try {
              errText = JSON.parse(xhr.responseText).detail || errText;
            } catch (e) {}
            statusEl.textContent = errText;
            statusEl.style.color = "var(--red)";
            resolve();
          }
        };

        xhr.onerror = () => {
          progressFill.classList.add("error");
          statusEl.textContent = "Network Error";
          statusEl.style.color = "var(--red)";
          resolve();
        };

        xhr.send(formData);
      });
    }

    isUploading = false;
    fileInput.value = "";
    loadFiles();
  }

  // Dropzone drag-and-drop
  dropzone.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => uploadFiles(Array.from(fileInput.files)));

  ["dragenter", "dragover"].forEach((evt) => {
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.add("dragover");
    });
  });

  ["dragleave", "drop"].forEach((evt) => {
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.remove("dragover");
    });
  });

  dropzone.addEventListener("drop", (e) => {
    if (e.dataTransfer && e.dataTransfer.files.length > 0) {
      uploadFiles(Array.from(e.dataTransfer.files));
    }
  });

  // Pair Modal Tabs & Actions
  function openPairModal(tab = "qr") {
    pairModal.classList.add("active");
    switchTab(tab);
    loadHostInfo();
  }

  function closePairModal() {
    pairModal.classList.remove("active");
  }

  function switchTab(tabId) {
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === tabId);
    });
    document.querySelectorAll(".tab-content").forEach((c) => {
      c.classList.toggle("active", c.id === `tab-${tabId}`);
    });
  }

  openPairModalBtn.addEventListener("click", () => openPairModal("qr"));
  closePairModalBtn.addEventListener("click", closePairModal);
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  // Submit pairing code
  document.getElementById("submitPinBtn").addEventListener("click", async () => {
    const pin = document.getElementById("inputPin").value.trim();
    const pinMsg = document.getElementById("pinMsg");
    if (!pin) {
      pinMsg.textContent = "Please enter a 6-digit code";
      pinMsg.style.color = "var(--red)";
      return;
    }
    pinMsg.textContent = "Submitting pairing request...";
    pinMsg.style.color = "var(--accent)";

    try {
      const res = await fetch("/api/pair/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          requester_id: clientInfo.id,
          requester_name: clientInfo.name,
          requester_type: clientInfo.type,
          pin: pin,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        pinMsg.textContent = data.detail || "Pairing failed";
        pinMsg.style.color = "var(--red)";
        return;
      }

      pinMsg.textContent = "Request sent! Awaiting approval on receiving device...";
      pinMsg.style.color = "var(--green)";

      // Poll request status
      const reqId = data.request_id;
      const pollInterval = setInterval(async () => {
        try {
          const sRes = await fetch(`/api/pair/request/${reqId}`);
          if (sRes.ok) {
            const sData = await sRes.json();
            if (sData.status === "approved") {
              clearInterval(pollInterval);
              pinMsg.textContent = "🎉 Paired successfully!";
              setTimeout(() => {
                closePairModal();
                loadDevices();
              }, 1200);
            } else if (sData.status === "rejected") {
              clearInterval(pollInterval);
              pinMsg.textContent = "Pairing request was declined by receiver.";
              pinMsg.style.color = "var(--red)";
            }
          }
        } catch (e) {}
      }, 1500);
    } catch (err) {
      pinMsg.textContent = "Network error while pairing";
      pinMsg.style.color = "var(--red)";
    }
  });

  // Submit Manual IP
  document.getElementById("submitIpBtn").addEventListener("click", async () => {
    const ip = document.getElementById("inputIp").value.trim();
    const ipMsg = document.getElementById("ipMsg");
    if (!ip) {
      ipMsg.textContent = "Please enter a valid IP address";
      ipMsg.style.color = "var(--red)";
      return;
    }

    try {
      const res = await fetch("/api/devices/discover", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ip: ip }),
      });
      if (res.ok) {
        ipMsg.textContent = "Device discovered! You can now pair with it.";
        ipMsg.style.color = "var(--green)";
        loadDevices();
      } else {
        ipMsg.textContent = "Failed to register IP";
        ipMsg.style.color = "var(--red)";
      }
    } catch (err) {
      ipMsg.textContent = "Network error";
      ipMsg.style.color = "var(--red)";
    }
  });

  // URL QR Scan auto-pairing check
  async function checkUrlPairing() {
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get("pair") === "1" || urlParams.get("pair") === "true") {
      const pin = urlParams.get("pin");
      const token = urlParams.get("token");

      if (pin || token) {
        try {
          const res = await fetch("/api/pair/request", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              requester_id: clientInfo.id,
              requester_name: clientInfo.name,
              requester_type: clientInfo.type,
              pin: pin,
              token: token,
            }),
          });
          if (res.ok) {
            const data = await res.json();
            // Show toast or banner
            alert(`Pairing request sent from ${clientInfo.name}! Please approve on the host laptop.`);
            // Clean URL query params without reloading
            window.history.replaceState({}, document.title, window.location.pathname);
          }
        } catch (e) {}
      }
    }
  }

  function escapeHtml(str) {
    if (!str) return "";
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  refreshFilesBtn.addEventListener("click", loadFiles);

  // Initial runs and polling
  loadHostInfo();
  loadDevices();
  loadFiles();
  checkUrlPairing();

  setInterval(() => {
    loadDevices();
    checkPairingRequests();
    checkIncomingTransfers();
  }, 2500);

  setInterval(loadHostInfo, 10000);
})();
