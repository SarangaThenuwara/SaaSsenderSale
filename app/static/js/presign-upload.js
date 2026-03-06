window.presignedUpload = async function (file, presignEndpoint, completeEndpoint, meta = {}) {
  // CLIENT-SIDE VALIDATION
  if (!file) throw new Error("No file selected");

  if (file.type !== "application/pdf") {
    throw new Error("Only PDF files are allowed.");
  }

  const MAX_SIZE = 2 * 1024 * 1024; // 2MB
  if (file.size > MAX_SIZE) {
    throw new Error("File size exceeds the 2MB limit.");
  }

  // 1) request presigned URL
  const form = new FormData();
  form.append("filename", file.name);
  form.append("content_type", "application/pdf");

  const csrf = document.getElementById("csrf_token")?.value || document.querySelector('input[name="csrf"]')?.value;

  const presignResp = await fetch(presignEndpoint, {
    method: "POST",
    headers: {
      "X-CSRF-Token": csrf
    },
    body: form
  });

  if (!presignResp.ok) {
    const err = await presignResp.json();
    throw new Error(err.error || "Failed to get presigned URL");
  }

  const { upload_url, key } = await presignResp.json();

  // 2) PUT (or POST) file with progress
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    // Worker expects POST for file upload
    xhr.open("POST", upload_url, true);
    // Explicitly setting Content-Type so it's not multipart/form-data
    xhr.setRequestHeader("Content-Type", "application/pdf");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 100);
        document.dispatchEvent(new CustomEvent("presign:progress", { detail: { pct } }));
      }
    };
    xhr.onload = async () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        // notify server the upload completed and associate key with user
        const completeResp = await fetch(completeEndpoint, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf
          },
          body: JSON.stringify({ key, filename: file.name, ...meta })
        });
        if (!completeResp.ok) {
          const err = await completeResp.json();
          reject(new Error(err.error || "Upload completed but server finalize failed"));
          return;
        }
        resolve(await completeResp.json());
      } else {
        reject(new Error(`Upload failed with status ${xhr.status}`));
      }
    };
    xhr.onerror = () => reject(new Error("Network error during upload"));
    xhr.send(file);
  });
}