
document.addEventListener("DOMContentLoaded", () => {
    const uploadArea = document.getElementById("upload-area");
    const cvFileInp = document.getElementById("cv_file");
    const progressBar = document.getElementById("progress-bar");
    const progressArea = document.getElementById("upload-progress");
    const progressPercent = document.getElementById("progress-percent");

    if (!uploadArea || !cvFileInp) return;

    // Click handler
    uploadArea.addEventListener("click", () => cvFileInp.click());

    // Input change handler
    cvFileInp.addEventListener("change", (e) => {
        if (e.target.files && e.target.files[0]) {
            handleUpload(e.target.files[0]);
        }
    });

    // Drag and drop handlers
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        uploadArea.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
        uploadArea.addEventListener(eventName, highlight, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        uploadArea.addEventListener(eventName, unhighlight, false);
    });

    function highlight(e) {
        uploadArea.classList.add('border-primary-500', 'bg-slate-800');
    }

    function unhighlight(e) {
        uploadArea.classList.remove('border-primary-500', 'bg-slate-800');
    }

    uploadArea.addEventListener('drop', handleDrop, false);

    function handleDrop(e) {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files && files[0]) {
            handleUpload(files[0]);
        }
    }

    async function handleUpload(file) {
        // Show progress
        progressArea.classList.remove("hidden");
        progressBar.style.width = "0%";
        progressPercent.innerText = "0%";

        // Listen for progress events from window.presignedUpload
        const onProgress = (e) => {
            const pct = e.detail.pct;
            progressBar.style.width = pct + "%";
            progressPercent.innerText = pct + "%";
        };
        document.addEventListener("presign:progress", onProgress);

        try {
            const csrf = document.getElementById("csrf_token")?.value;
            // NOTE: Our backend doesn't seem to enforce CSRF on the API endpoint based on main.py analysis?
            // But main.py presign endpoints are simple.

            // Passing metadata if needed (e.g. CSRF in headers?)
            // The fetch inside presignedUpload doesn't inject custom headers easily except via metadata form fields?
            // Actually presignedUpload uses `fetch(presignEndpoint)` with FormData.

            await window.presignedUpload(
                file,
                "/api/presign_upload",
                "/api/presign_complete"
            );

            // Success
            progressBar.classList.add("bg-green-500");
            progressPercent.innerText = "Done!";

            setTimeout(() => {
                window.location.reload();
            }, 1000);

        } catch (err) {
            console.error(err);
            progressBar.classList.add("bg-red-500");
            progressPercent.innerText = "Error";
            alert("Upload failed: " + err.message);
        } finally {
            document.removeEventListener("presign:progress", onProgress);
        }
    }
});
