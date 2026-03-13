
document.addEventListener("DOMContentLoaded", () => {
    const escapeHtml = (str) => {
        if (str === null || str === undefined) return "";
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    };

    const uploadArea = document.getElementById("upload-area");
    const cvFileInp = document.getElementById("cv_file");
    const progressBar = document.getElementById("progress-bar");
    const progressArea = document.getElementById("upload-progress");
    const progressPercent = document.getElementById("progress-percent");

    if (!uploadArea || !cvFileInp) return;

    // Click handler
    uploadArea.addEventListener("click", () => {
        const isActive = document.getElementById('toggle-campaign')?.dataset.active === 'true';
        if (isActive) {
            if (!confirm("Uploading a new CV will stop your running campaign. Continue?")) return;
        }
        cvFileInp.click();
    });

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
        // Enforce 2MB limit
        const maxMB = 2 * 1024 * 1024;
        if (file.size > maxMB) {
            alert("File too large. Maximum allowed size is 2MB.");
            return;
        }

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
                "/api/presign_complete",
                { filesize: file.size }
            );

            // Success
            progressBar.classList.add("bg-emerald-500");
            progressPercent.innerText = "Done!";

            // Immediate Visual Confirmation
            const area = document.getElementById("upload-area");
            const icon = document.getElementById("upload-status-icon");
            const text = document.getElementById("upload-area-text");
            const subtext = document.getElementById("upload-area-subtext");

            if (area) {
                area.classList.remove("border-white/5", "bg-slate-800/20");
                area.classList.add("border-emerald-500/50", "bg-emerald-500/5");
            }
            if (icon) {
                icon.innerHTML = '<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>';
                icon.classList.remove("bg-primary-500/10", "text-primary-400");
                icon.classList.add("bg-emerald-500/20", "text-emerald-400");
            }
            if (text) {
                text.innerText = "Resume Active & Verified";
                text.className = "text-sm text-emerald-400 font-bold mb-1 uppercase tracking-tight";
            }
            if (subtext) {
                subtext.innerText = file.name;
            }

            if (area && !document.getElementById("upload-replace-text")) {
                const replaceText = document.createElement("p");
                replaceText.id = "upload-replace-text";
                replaceText.className = "text-[9px] text-slate-400 mt-2 uppercase font-black animate-pulse";
                replaceText.innerText = "Click to replace current file";
                // Insert before the hidden inputs
                area.insertBefore(replaceText, document.getElementById("csrf_token"));
            }

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

    function timeAgo(date) {
        const seconds = Math.floor((new Date() - new Date(date)) / 1000);
        let interval = seconds / 31536000;
        if (interval > 1) return Math.floor(interval) + " years ago";
        interval = seconds / 2592000;
        if (interval > 1) return Math.floor(interval) + " months ago";
        interval = seconds / 86400;
        if (interval > 1) return Math.floor(interval) + " days ago";
        interval = seconds / 3600;
        if (interval > 1) return Math.floor(interval) + " hours ago";
        interval = seconds / 60;
        if (interval > 1) return Math.floor(interval) + " minutes ago";
        return Math.floor(seconds) + " seconds ago";
    }

    // --- Report Loading ---
    async function loadReport() {
        const reportBody = document.getElementById("report-body");
        if (!reportBody) return;

        try {
            const resp = await fetch("/api/user/report");
            const data = await resp.json();

            if (data.error) {
                reportBody.innerHTML = `<tr><td colspan="4" class="py-8 text-center text-red-400 text-sm">${data.error}</td></tr>`;
                return;
            }

            if (data.length === 0) {
                reportBody.innerHTML = `<tr><td colspan="4" class="py-12 text-center text-slate-500 italic text-sm">No outreach activity yet. Start your campaign to see results!</td></tr>`;
                return;
            }

            reportBody.innerHTML = data.map(r => {
                let statusLabel = r.status;
                let statusClass = 'bg-blue-500/10 text-blue-400';
                let guidance = r.last_error || 'Success';

                if (r.status === 'Sent') {
                    statusLabel = 'Delivered';
                    statusClass = 'bg-green-500/10 text-green-400';
                } else if (r.status === 'Failed') {
                    statusLabel = 'Action Needed';
                    statusClass = 'bg-red-500/10 text-red-400';
                    
                    if (guidance.toLowerCase().includes('token') || guidance.includes('401')) {
                        guidance = "Email connection expired. Please disconnect and reconnect your email in Settings.";
                    } else if (guidance.toLowerCase().includes('limit')) {
                        guidance = "Daily limit reached. The system will resume tomorrow.";
                    }
                }

                return `
                <tr class="hover:bg-white/2 transition-colors">
                    <td class="py-4">
                        <div class="flex flex-col">
                            <span class="text-sm font-medium text-white">${escapeHtml(r.email)}</span>
                            <span class="text-[10px] text-slate-500">${r.role || 'Recruiter'}</span>
                        </div>
                    </td>
                    <td class="py-4">
                        <span class="px-2.5 py-1 rounded-full text-[10px] font-bold ${statusClass}">
                            ${statusLabel}
                        </span>
                    </td>
                    <td class="py-4 text-xs text-slate-400">
                        ${r.sent_at ? timeAgo(r.sent_at) : '-'}
                    </td>
                    <td class="py-4 text-right">
                        <span title="${guidance}" class="text-[10px] text-slate-500 italic max-w-xs truncate block ml-auto cursor-help">
                            ${escapeHtml(guidance)}
                        </span>
                    </td>
                </tr>
            `}).join('');

        } catch (err) {
            console.error("Failed to load report", err);
        }
    }

    loadReport();

    // Refresh every 30 seconds if page is visible
    setInterval(() => {
        if (document.visibilityState === "visible") {
            loadReport();
        }
    }, 30000);
});

