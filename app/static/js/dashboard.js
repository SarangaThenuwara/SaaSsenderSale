
document.addEventListener("DOMContentLoaded", () => {
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

            reportBody.innerHTML = data.map(r => `
                <tr class="hover:bg-white/2 transition-colors">
                    <td class="py-4">
                        <div class="flex flex-col">
                            <span class="text-sm font-medium text-white">${r.email}</span>
                            <span class="text-[10px] text-slate-500">${r.role || 'Recruiter'}</span>
                        </div>
                    </td>
                    <td class="py-4">
                        <span class="px-2.5 py-1 rounded-full text-[10px] font-bold ${r.status === 'Sent' ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
                }">
                            ${r.status}
                        </span>
                    </td>
                    <td class="py-4 text-xs text-slate-400">
                        ${r.sent_at ? new Date(r.sent_at).toLocaleString() : '-'}
                    </td>
                    <td class="py-4 text-right">
                        <span class="text-[10px] text-slate-500 italic max-w-xs truncate block ml-auto">
                            ${r.last_error || 'Success'}
                        </span>
                    </td>
                </tr>
            `).join('');

        } catch (err) {
            console.error("Failed to load report", err);
        }
    }

    // --- Campaign Management ---
    const campaignList = document.getElementById("campaign-list");
    const modal = document.getElementById("modal-create-campaign");
    const btnCreate = document.getElementById("btn-create-campaign");
    const btnCancel = document.getElementById("btn-cancel-campaign");
    const btnSubmit = document.getElementById("btn-submit-campaign");
    const countrySelect = document.getElementById("new-camp-country");
    const providerSelect = document.getElementById("new-camp-provider");
    const docBody = document.body;

    async function loadCampaigns() {
        if (!campaignList) return;
        try {
            const resp = await fetch("/api/campaigns/");
            const campaigns = await resp.json();

            if (campaigns.length === 0) {
                campaignList.innerHTML = `<div class="text-center py-6 text-slate-500 text-sm">No campaigns found. Create a segment to start!</div>`;
                return;
            }

            campaignList.innerHTML = campaigns.map(c => {
                const isActive = c.status === "active";
                return `
                <div class="p-4 rounded-xl border ${isActive ? 'border-primary-500/50 bg-primary-500/5' : 'border-white/5 bg-white/2'} flex items-center justify-between group hover:border-white/10 transition-all">
                    <div>
                        <div class="flex items-center gap-3">
                            <h4 class="font-bold text-white text-sm">${c.name}</h4>
                            ${isActive ? '<span class="px-2 py-0.5 rounded-full bg-green-500/20 text-green-400 text-[10px] font-bold uppercase tracking-wider animate-pulse">Active</span>' : ''}
                        </div>
                        <div class="flex items-center gap-4 mt-2 text-xs text-slate-400">
                            <span>Pending: <span class="text-white font-medium">${c.pending_count}</span></span>
                            <span>Sent: <span class="text-white font-medium">${c.sent_count}</span></span>
                        </div>
                    </div>
                    
                    <div class="flex items-center gap-2"> 
                         ${!isActive ? `
                            <button onclick="window.activateCampaign('${c._id}')" class="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-white text-xs transition-colors border border-white/5 hover:border-white/10">
                                Activate
                            </button>
                         ` : `
                            <button onclick="window.pauseCampaign('${c._id}')" class="px-3 py-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-400 text-xs transition-colors border border-red-500/20">
                                Pause
                            </button>
                         `}
                    </div>
                </div>
                `;
            }).join('');

        } catch (err) {
            console.error("Failed to load campaigns", err);
        }
    }

    async function loadFilters() {
        if (!countrySelect) return;
        try {
            const resp = await fetch("/api/campaigns/filters");
            const data = await resp.json();

            if (data.countries) {
                countrySelect.innerHTML = '<option value="">All Countries</option>' +
                    data.countries.map(c => `<option value="${c}">${c}</option>`).join('');
            }
            if (data.providers) {
                providerSelect.innerHTML = '<option value="">All Types</option>' +
                    data.providers.map(p => `<option value="${p}">${p}</option>`).join('');
            }
        } catch (err) {
            console.error("Failed to load filters", err);
        }
    }

    function initCampaignModal() {
        if (!modal) return;

        btnCreate?.addEventListener("click", () => {
            modal.classList.remove("hidden");
            // small delay to allow display:block to apply before opacity transition
            setTimeout(() => modal.classList.remove("opacity-0"), 10);
            document.getElementById("modal-content").classList.remove("scale-95");
            document.getElementById("modal-content").classList.add("scale-100");
        });

        const closeModal = () => {
            modal.classList.add("opacity-0");
            document.getElementById("modal-content").classList.remove("scale-100");
            document.getElementById("modal-content").classList.add("scale-95");
            setTimeout(() => modal.classList.add("hidden"), 300);
        };

        btnCancel?.addEventListener("click", closeModal);

        // Close on background click
        modal.addEventListener("click", (e) => {
            if (e.target === modal) closeModal();
        });

        btnSubmit?.addEventListener("click", async () => {
            const name = document.getElementById("new-camp-name").value;
            const country = countrySelect.value;
            const provider = providerSelect.value;

            if (!name) { alert("Please enter a campaign name"); return; }
            if (!confirm(`Create segment "${name}" and move matching leads from your pool?`)) return;

            btnSubmit.innerText = "Creating...";
            btnSubmit.disabled = true;

            try {
                const filters = {};
                if (country) filters.country = country;
                if (provider) filters.provider = provider;

                const res = await fetch("/api/campaigns/", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ name, filters })
                });
                const data = await res.json();
                if (data.ok) {
                    closeModal();
                    loadCampaigns();
                    // clear form
                    document.getElementById("new-camp-name").value = "";
                } else {
                    alert("Error: " + (data.detail || "Failed to create campaign"));
                }
            } catch (err) {
                alert("Error: " + err.message);
            } finally {
                btnSubmit.innerText = "Create Segment";
                btnSubmit.disabled = false;
            }
        });
    }

    // Expose global functions for button clicks
    window.activateCampaign = async (id) => {
        if (!confirm("Start this segment? This will lock a SNAPSHOT of your current CV and templates for this run. Updates to settings won't apply until you restart.")) return;
        try {
            const res = await fetch(`/api/campaigns/${id}/start`, { method: "POST" });
            if (res.ok) {
                loadCampaigns();
                // update top bar status implicitly by reload or just let status cycle?
                // Reloading page might be best to update global state in top bar
                window.location.reload();
            } else {
                alert("Failed to activate");
            }
        } catch (err) { alert(err.message); }
    };

    window.pauseCampaign = async (id) => {
        if (!confirm("Pause this segment? Sending will stop for all recipients in this group.")) return;
        try {
            const res = await fetch(`/api/campaigns/${id}/pause`, { method: "POST" });
            if (res.ok) {
                loadCampaigns();
                window.location.reload();
            } else {
                alert("Failed to pause");
            }
        } catch (err) { alert(err.message); }
    };

    loadReport();
    loadCampaigns();
    loadFilters();
    initCampaignModal();

    // Refresh every 30 seconds if page is visible
    setInterval(() => {
        if (document.visibilityState === "visible") {
            loadReport();
            loadCampaigns();
        }
    }, 30000);
});

