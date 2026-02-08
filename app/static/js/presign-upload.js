// Minimal helper for presigned PUT + progress.
window.presignedUpload = async function (file, presignEndpoint, completeEndpoint, metadata = {}) {
  // 1) request presigned URL
  const form = new FormData();
  form.append("filename", file.name);
  form.append("content_type", file.type || "application/pdf");
  for (const k in metadata) form.append(k, metadata[k]);

  const presignResp = await fetch(presignEndpoint, { method: "POST", body: form });
  if (!presignResp.ok) throw new Error("Failed to get presigned URL");
  const { upload_url, key } = await presignResp.json();

  // 2) PUT file with progress
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", upload_url, true);
    xhr.setRequestHeader("Content-Type", file.type || "application/pdf");
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
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key, filename: file.name })
        });
        if (!completeResp.ok) {
          reject(new Error("Upload completed but server finalize failed"));
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