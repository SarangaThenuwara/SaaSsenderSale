/**
 * Premium Admin Dashboard Engine
 */

const AdminDashboard = {
    // State
    state: {
        users: { page: 1, limit: 12, q: "", total: 0, totalPages: 0 },
        recruiters: { page: 1, limit: 50, q: "", total: 0, totalPages: 0 },
        activeTab: 'users',
        volumeChart: null
    },

    // API Helpers
    async fetchSecure(url, options = {}) {
        const method = options.method || 'GET';
        const headers = {
            'X-CSRF-Token': document.querySelector('input[name="csrf"]')?.value,
            ...options.headers
        };
        
        // Handle params for GET
        let targetUrl = url;
        if (method === 'GET' && options.params) {
            const query = new URLSearchParams(options.params).toString();
            targetUrl = `${url}?${query}`;
        }

        let body = options.body;
        if (body && typeof body === 'object' && !(body instanceof FormData)) {
            body = JSON.stringify(body);
            headers['Content-Type'] = 'application/json';
        }
        
        try {
            const response = await fetch(targetUrl, { method, headers, body });
            const data = await response.json();
            
            // Handle encrypted response
            if (data && data.enc) {
                const decryptRes = await fetch('/api/admin/decrypt', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRF-Token': document.querySelector('input[name="csrf"]')?.value
                    },
                    body: JSON.stringify(data)
                });
                return await decryptRes.json();
            }
            return data;
        } catch (err) {
            console.error(`API Error [${url}]:`, err);
            this.showToast('Secure Fetch Failed', 'error');
            throw err;
        }
    },

    init() {
        console.log("Initializing Dashboard Engine...");
        this.setupTabs();
        this.initCharts();
        this.setupSearch();
        this.setupActions();
        
        // Initial load
        this.loadUsers();
        this.loadSummaryStats();
        
        // Start live sync (activity monitor)
        this.startActivityMonitor();
        
        // Refresh stats every 60s
        setInterval(() => this.loadSummaryStats(), 60000);
    },

    setupTabs() {
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const target = btn.dataset.target?.replace('panel-', '') || btn.dataset.tab;
                if (target) {
                    e.preventDefault();
                    this.switchTab(target);
                }
            });
        });
    },

    switchTab(tabId) {
        // UI
        document.querySelectorAll('.tab-btn').forEach(b => {
             const bTarget = b.dataset.target?.replace('panel-', '') || b.dataset.tab;
             b.classList.toggle('active-tab-btn', bTarget === tabId);
             b.classList.toggle('active', bTarget === tabId);
        });
        
        document.querySelectorAll('.panel-content, .tab-content').forEach(p => {
             const pId = p.id.replace('panel-', '').replace('tab-', '');
             p.classList.toggle('hidden', pId !== tabId);
        });
        
        this.state.activeTab = tabId;
        
        // Loader
        switch(tabId) {
            case 'users': this.loadUsers(); break;
            case 'recruiters': this.loadRecruiters(); break;
            case 'infra': this.loadInfra(); break;
            case 'policy': this.loadPolicy(); break;
            case 'nodes': this.loadNodes(); break;
            case 'moderation': this.loadModeration(); break;
            case 'deliverability': this.loadDeliverability(); break;
        }
    },

    async initCharts() {
        const ctx = document.getElementById('volumeChart')?.getContext('2d');
        if (!ctx) return;

        try {
            const data = await this.fetchSecure('/api/admin/volume_data');
            
            const gradient = ctx.createLinearGradient(0, 0, 0, 100);
            gradient.addColorStop(0, 'rgba(34, 197, 94, 0.4)');
            gradient.addColorStop(1, 'rgba(34, 197, 94, 0)');

            this.state.volumeChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: data.labels,
                    datasets: [{
                        label: 'SuccessRate',
                        data: data.success_rate,
                        borderColor: '#22c55e',
                        borderWidth: 2,
                        fill: true,
                        backgroundColor: gradient,
                        tension: 0.4,
                        pointRadius: 0
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { 
                        legend: { display: false },
                        tooltip: {
                            enabled: true,
                            backgroundColor: '#0f172a',
                            titleColor: '#94a3b8',
                            bodyColor: '#fff',
                            bodyFont: { weight: 'bold' },
                            callbacks: {
                                label: (ctx) => ` Success: ${ctx.raw}%`
                            }
                        }
                    },
                    scales: {
                        x: { display: false },
                        y: { display: false, min: 0, max: 100 }
                    }
                }
            });
        } catch (err) {
            console.error("Chart Init Failed:", err);
        }
    },

    setupSearch() {
        const userSearch = document.getElementById('user-search');
        if (userSearch) {
            let timeout;
            userSearch.addEventListener('input', (e) => {
                clearTimeout(timeout);
                timeout = setTimeout(() => {
                    this.state.users.q = e.target.value;
                    this.state.users.page = 1;
                    this.loadUsers();
                }, 300);
            });
        }

        const recSearch = document.getElementById('recruiter-search');
        if (recSearch) {
            let timeout;
            recSearch.addEventListener('input', (e) => {
                clearTimeout(timeout);
                timeout = setTimeout(() => {
                    this.state.recruiters.q = e.target.value;
                    this.state.recruiters.page = 1;
                    this.loadRecruiters();
                }, 400);
            });
        }

        const traceQuery = document.getElementById('trace-query');
        if (traceQuery) {
            traceQuery.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') this.triggerTrace();
            });
        }
    },

    async triggerTrace() {
        const query = document.getElementById('trace-query')?.value;
        if (!query) return;
        
        const body = document.getElementById('trace-results-body');
        if (body) body.innerHTML = '<tr><td colspan="4" class="py-12 text-center text-slate-500 animate-pulse">Scanning ledger archives...</td></tr>';

        try {
            const data = await this.fetchSecure('/api/admin/message_trace', { params: { query } });
            if (body) {
                body.innerHTML = data.results.map(l => `
                    <tr>
                        <td class="py-3">
                            <p class="text-white font-bold">${this.escape(l.email)}</p>
                            <p class="text-[9px] text-slate-500 font-mono">${this.escape(l.domain || 'N/A')}</p>
                        </td>
                        <td class="py-3 text-center text-slate-500 font-mono text-[10px]">${l.userId}</td>
                        <td class="py-3 text-center">
                            <span class="px-2 py-1 rounded text-[9px] font-black uppercase tracking-widest ${this.getStatusColor(l.status)}">${l.status}</span>
                        </td>
                        <td class="py-3 text-right text-slate-600 font-mono text-[10px]">${new Date(l.updated_at).toLocaleString()}</td>
                    </tr>
                `).join('') || '<tr><td colspan="4" class="py-12 text-center text-slate-700 uppercase tracking-widest text-[10px] font-black">No matching records found</td></tr>';
            }
        } catch (err) {}
    },

    async loadUsers() {
        const tbody = document.getElementById('user-table-body');
        if (!tbody) return;

        try {
            const data = await this.fetchSecure('/api/admin/users', {
                params: {
                    page: this.state.users.page,
                    limit: this.state.users.limit,
                    q: this.state.users.q
                }
            });

            this.state.users.total = data.total;
            this.state.users.totalPages = data.total_pages;

            tbody.innerHTML = data.users.length ? data.users.map(u => this.renderUserRow(u)).join('') : `
                <tr><td colspan="5" class="py-12 text-center text-slate-500 font-bold uppercase tracking-widest text-[10px]">No users found for identity match</td></tr>
            `;

            this.renderPagination('users-pagination', this.state.users, (page) => {
                this.state.users.page = page;
                this.loadUsers();
            });

        } catch (err) {
            tbody.innerHTML = `<tr><td colspan="5" class="py-12 text-center text-red-500/50">Runtime Exception: Failed to list identity pool</td></tr>`;
        }
    },

    renderUserRow(u) {
        const initials = u.username ? u.username.slice(0, 2).toUpperCase() : '??';
        const isLocked = u.locked_until && new Date(u.locked_until) > new Date();
        
        return `
            <tr class="user-row hover:bg-white/[0.02] transition-colors">
                <td class="px-6 py-4">
                    <div class="flex items-center gap-3">
                        <div class="h-8 w-8 rounded-lg bg-primary-500/10 flex items-center justify-center text-[10px] font-bold text-primary-400 border border-primary-500/10">
                            ${initials}
                        </div>
                        <div>
                            <p class="font-bold text-white flex items-center gap-2">
                                ${u.username}
                                ${isLocked ? '<span class="text-[8px] bg-red-500 text-white px-1 rounded uppercase tracking-wider font-black">LOCKED</span>' : ''}
                            </p>
                            <div class="flex items-center gap-1.5 mt-0.5">
                                <p class="text-[9px] text-slate-500 font-mono">${u.email}</p>
                                <span class="text-[9px] text-primary-500/50">&bull;</span>
                                <p class="text-[9px] text-slate-500 font-mono">${u.last_login_ip || 'No record'}</p>
                            </div>
                        </div>
                    </div>
                </td>
                <td class="px-6 py-4 text-center">
                    <button data-email="${u.email}"
                        class="btn-verify-dns px-2 py-0.5 bg-white/5 border border-white/5 rounded text-[8px] font-black tracking-widest text-slate-500 hover:text-white transition-all uppercase">DNS CHECK</button>
                </td>
                <td class="px-6 py-4 text-center">
                    ${u.campaign_active ? 
                        '<span class="px-2 py-0.5 bg-green-500/10 text-green-400 text-[9px] font-black rounded border border-green-500/10">RUNNING</span>' : 
                        '<span class="px-2 py-0.5 bg-slate-800 text-slate-500 text-[9px] font-black rounded">HALTED</span>'}
                </td>
                <td class="px-6 py-4 text-center">
                    <div class="flex flex-col items-center">
                        <span class="text-xs font-bold ${u.is_paid ? 'text-primary-400' : 'text-slate-500'}">${u.is_paid ? 'PREMIUM' : 'FREE'}</span>
                        ${u.is_paid && u.subscription_expires_at ? `<span class="text-[8px] text-slate-600 font-mono mt-0.5">${new Date(u.subscription_expires_at).toLocaleDateString()}</span>` : ''}
                        ${!u.is_paid ? `<button class="text-[8px] text-primary-500/50 hover:text-primary-500 underline mt-1 action-upgrade" data-id="${u._id}">UPGRADE</button>` : ''}
                    </div>
                </td>
                <td class="px-6 py-4 text-right">
                    <div class="flex justify-end gap-2">
                        <button class="action-block p-2 rounded bg-white/5 hover:bg-white/10 ${u.is_blocked ? 'text-red-500' : 'text-slate-400'}" data-id="${u._id}" data-blocked="${u.is_blocked}" title="${u.is_blocked ? 'Unblock' : 'Block'}">
                            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728L5.636 5.636"/></svg>
                        </button>
                        <button class="action-delete p-2 rounded bg-red-500/10 hover:bg-red-500/20 text-red-500" data-id="${u._id}" title="Delete">
                            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                        </button>
                        <button class="action-impersonate p-2 rounded bg-blue-500/10 hover:bg-blue-500/20 text-blue-500" data-id="${u._id}" title="Impersonate">
                            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 16l-4-4m0 0l4-4m-4 4h14m-5 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h7a3 3 0 013 3v1"/></svg>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    },

    renderPagination(id, state, callback) {
        const el = document.getElementById(id);
        if (!el) return;

        if (state.totalPages <= 1) {
            el.innerHTML = '';
            return;
        }

        const pages = [];
        
        // Prev button
        pages.push(`
            <button class="h-8 px-2 rounded flex items-center justify-center font-bold text-[10px] uppercase tracking-widest ${state.page > 1 ? 'bg-white/5 text-slate-400 hover:text-white hover:bg-white/10 cursor-pointer' : 'text-slate-600 opacity-50 cursor-not-allowed'}"
                data-page="${Math.max(1, state.page - 1)}" ${state.page === 1 ? 'disabled' : ''}>Prev</button>
        `);

        // Sliding window logic
        let startPage = Math.max(1, state.page - 2);
        let endPage = Math.min(state.totalPages, startPage + 4);
        if (endPage - startPage < 4) {
            startPage = Math.max(1, endPage - 4);
        }

        if (startPage > 1) {
            pages.push(`<button class="h-8 w-8 rounded flex items-center justify-center font-mono bg-white/5 text-slate-500 hover:text-white transition-colors cursor-pointer" data-page="1">1</button>`);
            if (startPage > 2) pages.push(`<span class="text-slate-600 font-bold px-1">...</span>`);
        }

        for (let i = startPage; i <= endPage; i++) {
            pages.push(`
                <button class="h-8 w-8 rounded flex items-center justify-center font-mono ${state.page === i ? 'bg-primary-500 text-white shadow-lg shadow-primary-500/20 cursor-default' : 'bg-white/5 text-slate-500 hover:text-white transition-colors cursor-pointer'}" 
                    ${state.page !== i ? `data-page="${i}"` : ''}>${i}</button>
            `);
        }

        if (endPage < state.totalPages) {
            if (endPage < state.totalPages - 1) pages.push(`<span class="text-slate-600 font-bold px-1">...</span>`);
            pages.push(`<button class="h-8 w-8 rounded flex items-center justify-center font-mono bg-white/5 text-slate-500 hover:text-white transition-colors cursor-pointer" data-page="${state.totalPages}">${state.totalPages}</button>`);
        }

        // Next button
        pages.push(`
            <button class="h-8 px-2 rounded flex items-center justify-center font-bold text-[10px] uppercase tracking-widest ${state.page < state.totalPages ? 'bg-white/5 text-slate-400 hover:text-white hover:bg-white/10 cursor-pointer' : 'text-slate-600 opacity-50 cursor-not-allowed'}"
                data-page="${Math.min(state.totalPages, state.page + 1)}" ${state.page === state.totalPages ? 'disabled' : ''}>Next</button>
        `);

        el.innerHTML = `
            <div class="flex items-center gap-2">
                <span class="text-[10px] text-slate-500 uppercase tracking-widest font-bold hidden sm:inline-block">Page <span class="text-white">${state.page}</span> of ${state.totalPages}</span>
                <span class="mx-2 h-4 w-px bg-white/10 hidden sm:inline-block"></span>
                <div class="flex items-center gap-1">${pages.join('')}</div>
            </div>
            <div class="text-[10px] text-slate-500 uppercase tracking-widest font-bold mt-2 sm:mt-0">Total: <span class="text-white">${state.total.toLocaleString()}</span></div>
        `;

        el.querySelectorAll('button[data-page]').forEach(b => {
            b.addEventListener('click', (e) => {
                e.preventDefault();
                if (!b.disabled) callback(parseInt(b.dataset.page));
            });
        });
    },


    async loadSummaryStats() {
        try {
            const stats = await this.fetchSecure('/api/admin/stats');
            this.updateCounter('stat-total-users', stats.total_users);
            this.updateCounter('stat-total-sent', stats.total_sent_today);
            this.updateCounter('stat-recruiters', stats.total_recruiters);
        } catch (err) {}
    },

    updateCounter(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value.toLocaleString();
    },

    async loadRecruiters() {
        const tbody = document.getElementById('recruiters-table-body');
        if (!tbody) return;

        try {
            const data = await this.fetchSecure('/api/admin/recruiters', {
                params: {
                    page: this.state.recruiters.page,
                    limit: this.state.recruiters.limit,
                    search: this.state.recruiters.q
                }
            });

            this.state.recruiters.total = data.total;
            this.state.recruiters.totalPages = Math.ceil(data.total / this.state.recruiters.limit);

            tbody.innerHTML = data.items.map(r => `
                <tr class="hover:bg-white/[0.02] transition-colors">
                    <td class="px-6 py-4">
                        <p class="font-bold text-white select-all">${r.email}</p>
                        <p class="text-[9px] text-slate-600 font-mono">ID: ${r._id.slice(-6)}</p>
                    </td>
                    <td class="px-6 py-4 text-center text-xs text-slate-400">${r.detectedCountry || 'Unspecified'}</td>
                    <td class="px-6 py-4 text-center">
                        <span class="px-2 py-0.5 rounded text-[9px] font-bold tracking-tighter border 
                            ${r.health === 'good' ? 'bg-green-500/10 text-green-400 border-green-500/10' :
                              r.health === 'dead' ? 'bg-red-500/10 text-red-400 border-red-500/10' : 'bg-amber-500/10 text-amber-400 border-amber-500/10'}">
                            ${(r.health || 'UNKNOWN').toUpperCase()}
                        </span>
                    </td>
                    <td class="px-6 py-4 text-right">
                        <button class="btn-edit-recruiter px-3 py-1 bg-white/5 border border-white/10 rounded text-[10px] text-primary-400 hover:bg-white/10 transition-all font-bold" 
                            data-id="${r._id}" data-country="${r.detectedCountry || ''}" data-health="${r.health}" data-override="${r.manual_override || false}">Edit</button>
                    </td>
                </tr>
            `).join('') || '<tr><td colspan="4" class="py-12 text-center text-slate-500 font-bold uppercase tracking-widest text-[10px]">No recruiters match current parameters</td></tr>';

            this.renderPagination('recruiters-pagination', this.state.recruiters, (page) => {
                this.state.recruiters.page = page;
                this.loadRecruiters();
            });

            const badge = document.getElementById('recruiter-total-badge');
            if (badge) badge.textContent = `${data.total.toLocaleString()} emails`;

        } catch (err) {
            tbody.innerHTML = `<tr><td colspan="4" class="py-12 text-center text-red-500/50">Recruiter Pool Link Error</td></tr>`;
        }
    },

    async loadModeration() {
        const list = document.getElementById('moderation-list');
        if (!list) return;

        try {
            const users = await this.fetchSecure('/api/admin/content_review');
            if (!users || users.length === 0) {
                list.innerHTML = '<div class="py-12 text-center text-slate-500 italic">No user content found for review.</div>';
                return;
            }

            list.innerHTML = users.map(u => {
                const templates = u.templates || [];
                const emailCount = templates.length > 0 ? templates.length : (u.body ? 1 : 0);

                let templatesHtml = templates.length > 0 ? templates.map((t, idx) => `
                    <div class="mt-4 p-4 bg-slate-950 rounded-xl border border-white/5">
                        <p class="text-[10px] text-slate-500 uppercase font-black mb-2">Variation ${idx + 1}</p>
                        <p class="text-sm font-bold text-white mb-2">${this.escape(t.subject)}</p>
                        <div class="text-xs text-slate-400 whitespace-pre-wrap font-mono bg-black/50 p-3 rounded-lg border border-white/5 overflow-x-auto">${this.escape(t.body)}</div>
                    </div>
                `).join('') : (u.body ? `
                    <div class="mt-4 p-4 bg-slate-950 rounded-xl border border-white/5">
                        <p class="text-[10px] text-slate-500 uppercase font-black mb-2">Legacy Template</p>
                        <p class="text-sm font-bold text-white mb-2">${this.escape(u.subject)}</p>
                        <div class="text-xs text-slate-400 whitespace-pre-wrap font-mono bg-black/50 p-3 rounded-lg border border-white/5 overflow-x-auto">${this.escape(u.body)}</div>
                    </div>
                ` : `<p class="text-xs text-slate-500 italic mt-4">No templates configured.</p>`);

                return `
                    <div class="bg-slate-950/50 border border-white/5 rounded-2xl p-6">
                        <div class="flex items-start justify-between">
                            <div>
                                <div class="flex items-center gap-3 mb-1">
                                    <h4 class="font-bold text-white text-lg">${this.escape(u.username)}</h4>
                                    <span class="px-2 py-0.5 rounded text-[8px] font-black uppercase tracking-widest text-primary-400 bg-primary-500/10 border border-primary-500/10">${emailCount} TEMPLATES</span>
                                </div>
                                <p class="text-xs text-slate-500 font-mono">${this.escape(u.email)}</p>
                            </div>
                            <div class="flex gap-2">
                                <button data-id="${u.user_id}" data-username="${this.escape(u.username)}" class="btn-warn-user px-3 py-1.5 bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/20 text-amber-500 text-[10px] font-black uppercase rounded-lg transition-all">Issue Warning</button>
                                <button data-id="${u.user_id}" data-username="${this.escape(u.username)}" class="btn-ban-user px-3 py-1.5 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-500 text-[10px] font-black uppercase rounded-lg transition-all">Ban Sender</button>
                            </div>
                        </div>
                        <div class="mt-4 border-t border-white/5 pt-2">${templatesHtml}</div>
                    </div>
                `;
            }).join('');
        } catch (err) {}
    },

    async loadDeliverability() {
        try {
            const data = await this.fetchSecure('/api/admin/bounces/stats');
            
            const breakdown = document.getElementById('deliverability-breakdown');
            if (breakdown) {
                const max = Math.max(...data.by_provider.map(p => p.count), 1);
                breakdown.innerHTML = data.by_provider.map(p => `
                    <div class="space-y-1.5">
                        <div class="flex justify-between text-[10px] font-bold text-slate-600 uppercase tracking-widest">
                            <span>${p._id}</span>
                            <span class="text-white">${p.count} ERRORS</span>
                        </div>
                        <div class="h-1 bg-white/5 rounded-full overflow-hidden">
                            <div class="h-full bg-primary-500 shadow-[0_0_8px_rgba(59,130,246,0.3)]" style="width: ${(p.count / max * 100)}%"></div>
                        </div>
                    </div>
                `).join('');
            }

            const risky = document.getElementById('risky-users-container');
            if (risky) {
                if (data.risky_users.length === 0) {
                    risky.innerHTML = '<div class="py-12 text-center text-slate-600 italic text-xs">No active account anomalies found.</div>';
                } else {
                    risky.innerHTML = data.risky_users.map(u => `
                        <div class="p-4 flex items-center justify-between hover:bg-white/[0.01] transition-all">
                            <div>
                                <p class="text-sm font-bold text-white">${u.username}</p>
                                <p class="text-[10px] text-slate-500 font-mono">${u.email}</p>
                            </div>
                            <div class="text-right">
                                <p class="text-xs font-black text-red-500 tracking-tighter">${u.rate}% BOUNCE RATE</p>
                                <p class="text-[9px] text-slate-600 uppercase font-bold">${u.bounces_today} Hard Failures Today</p>
                            </div>
                        </div>
                    `).join('');
                }
            }
        } catch (err) {}
    },

    async loadInfra() {
        try {
            const data = await this.fetchSecure('/api/admin/infra');
            const resContainer = document.getElementById('sys-resource-stats');
            if (resContainer) {
                resContainer.innerHTML = `
                    <div class="space-y-4">
                        <div>
                            <div class="flex justify-between text-xs mb-1">
                                <span class="text-slate-500">CPU Usage</span>
                                <span class="text-white font-bold">${data.system.cpu}%</span>
                            </div>
                            <div class="h-1.5 bg-white/5 rounded-full overflow-hidden">
                                <div class="h-full bg-primary-500" style="width: ${data.system.cpu}%"></div>
                            </div>
                        </div>
                        <div>
                            <div class="flex justify-between text-xs mb-1">
                                <span class="text-slate-500">Memory</span>
                                <span class="text-white font-bold">${data.system.memory_pct}%</span>
                            </div>
                            <div class="h-1.5 bg-white/5 rounded-full overflow-hidden">
                                <div class="h-full bg-green-500" style="width: ${data.system.memory_pct}%"></div>
                            </div>
                        </div>
                        <div class="pt-4 grid grid-cols-2 gap-4 text-[10px]">
                            <div class="p-3 bg-white/5 rounded-lg">
                                <p class="text-slate-500 uppercase mb-1">Public IP</p>
                                <p class="text-white font-mono">${data.system.public_ip}</p>
                            </div>
                            <div class="p-3 bg-white/5 rounded-lg">
                                <p class="text-slate-500 uppercase mb-1">Local IP</p>
                                <p class="text-white font-mono">${data.system.local_ip}</p>
                            </div>
                        </div>
                    </div>
                `;
            }

           const dbContainer = document.getElementById('db-utilization-stats');
            if (dbContainer && data.databases.mongo) {
                const local = data.databases.mongo.local || {};
                const source = data.databases.mongo.source || {};

                dbContainer.innerHTML = `
                    <div class="space-y-4">
                        <div class="p-4 bg-white/5 rounded-xl border border-white/5">
                            <div class="flex items-center gap-2 mb-3">
                                <div class="w-2 h-2 rounded-full bg-primary-500 animate-pulse"></div>
                                <p class="text-[10px] text-slate-500 font-bold uppercase tracking-widest">SaaS Sender (Local)</p>
                            </div>
                            <div class="flex justify-between items-end">
                                <span class="text-2xl font-black text-white">${(local.count || 0).toLocaleString()} <span class="text-[10px] text-slate-500 font-normal">Docs</span></span>
                                <span class="text-[10px] text-slate-600 font-mono">Storage: ${local.storage || 0}MB</span>
                            </div>
                            <div class="mt-3 pt-3 border-t border-white/5 flex justify-between text-[9px] text-slate-600 font-mono uppercase">
                                <span>Index Size: ${local.indexes || 0}MB</span>
                                <span>Collection: recruiters</span>
                            </div>
                        </div>

                        <div class="p-4 bg-white/5 rounded-xl border border-white/5">
                            <div class="flex items-center gap-2 mb-3">
                                <div class="w-2 h-2 rounded-full bg-emerald-500"></div>
                                <p class="text-[10px] text-slate-500 font-bold uppercase tracking-widest">Recruiter (Source)</p>
                            </div>
                            <div class="flex justify-between items-end">
                                <span class="text-2xl font-black text-white">${(source.count || 0).toLocaleString()} <span class="text-[10px] text-slate-500 font-normal">Docs</span></span>
                                <span class="text-[10px] text-slate-600 font-mono">Storage: ${source.storage || 0}MB</span>
                            </div>
                            <div class="mt-3 pt-3 border-t border-white/5 flex justify-between text-[9px] text-slate-600 font-mono uppercase">
                                <span>Index Size: ${source.indexes || 0}MB</span>
                                <span>Collection: hremail.email</span>
                            </div>
                        </div>
                    </div>
                `;
            }

            // REDIS Display (New Request)
            const redisContainer = document.getElementById('redis-infra-stats');
            if (redisContainer && data.databases.redis) {
                const r = data.databases.redis;
                if (r.ok) {
                    redisContainer.innerHTML = `
                        <div class="p-4 bg-white/5 rounded-xl border border-white/5">
                            <div class="flex items-center justify-between mb-4">
                                <div class="flex items-center gap-2">
                                    <div class="w-2 h-2 rounded-full bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.5)]"></div>
                                    <p class="text-[10px] text-slate-500 font-bold uppercase tracking-widest">Redis Instance</p>
                                </div>
                                <span class="text-[9px] font-mono text-slate-600">v${r.version}</span>
                            </div>
                            <div class="grid grid-cols-2 gap-4 mb-4">
                                <div>
                                    <p class="text-[9px] text-slate-600 uppercase mb-1">Used Memory</p>
                                    <p class="text-lg font-black text-white">${r.used_memory}</p>
                                </div>
                                <div>
                                    <p class="text-[9px] text-slate-600 uppercase mb-1">Peak</p>
                                    <p class="text-lg font-black text-white">${r.peak_memory}</p>
                                </div>
                            </div>
                            <div class="space-y-2 pt-4 border-t border-white/5">
                                <div class="flex justify-between text-[10px]">
                                    <span class="text-slate-500">Hit Rate</span>
                                    <span class="text-white font-bold">${r.hit_rate}%</span>
                                </div>
                                <div class="flex justify-between text-[10px]">
                                    <span class="text-slate-500">Connected Clients</span>
                                    <span class="text-white font-bold">${r.clients}</span>
                                </div>
                                <div class="flex justify-between text-[10px]">
                                    <span class="text-slate-500">Total Keys</span>
                                    <span class="text-white font-bold">${r.keys.toLocaleString()}</span>
                                </div>
                            </div>
                        </div>
                    `;
                } else {
                    redisContainer.innerHTML = `<div class="p-4 bg-red-500/10 border border-red-500/20 rounded-xl text-center text-red-400 text-[10px] uppercase font-bold">Redis Connection Failure: ${r.error}</div>`;
                }
            }

            const netContainer = document.getElementById('network-infra-stats');
            if (netContainer) {
                netContainer.innerHTML = `
                    <div class="space-y-6">
                        <div class="p-4 bg-white/5 rounded-xl border border-white/5">
                            <p class="text-[10px] text-slate-500 font-bold uppercase tracking-widest mb-3">Throughput</p>
                            <div class="grid grid-cols-2 gap-4">
                                <div>
                                    <p class="text-[9px] text-slate-600 uppercase">Outgoing</p>
                                    <p class="text-lg font-black text-white">${data.system.net_sent} MB</p>
                                </div>
                                <div>
                                    <p class="text-[9px] text-slate-600 uppercase">Incoming</p>
                                    <p class="text-lg font-black text-white">${data.system.net_recv} MB</p>
                                </div>
                            </div>
                        </div>
                        <div class="space-y-2">
                             <p class="text-[10px] text-slate-500 font-bold uppercase tracking-widest">Host Context</p>
                             <div class="flex justify-between items-center text-xs">
                                <span class="text-slate-600">Hostname</span>
                                <span class="text-white font-mono">${data.system.hostname}</span>
                             </div>
                             <div class="flex justify-between items-center text-xs">
                                <span class="text-slate-600">Uptime</span>
                                <span class="text-emerald-500 font-mono uppercase">${data.system.uptime}</span>
                             </div>
                        </div>
                    </div>
                `;
            }
        } catch (err) {}
    },

    async loadPolicy() {
        try {
            const settings = await this.fetchSecure('/api/admin/settings');
            const revenue = await this.fetchSecure('/api/admin/revenue');
            const form = document.getElementById('system-settings-form');
            if (!form) return;

            // Update Revenue UI
            const revContainer = document.getElementById('revenue-stats');
            if (revContainer) {
                revContainer.innerHTML = `
                    <div class="space-y-4">
                        <div class="flex items-end justify-between">
                            <p class="text-3xl font-black text-white">${revenue.mrr.toLocaleString()} <span class="text-xs text-slate-500 font-normal">${revenue.currency}</span></p>
                            <span class="text-[10px] text-green-500 font-mono">+${revenue.new_subs_30d} new</span>
                        </div>
                        <div class="p-3 bg-white/5 rounded-xl border border-white/5">
                            <div class="flex justify-between items-center text-xs">
                                <span class="text-slate-500">Paid Subscribers</span>
                                <span class="text-white font-bold">${revenue.total_paid_users}</span>
                            </div>
                        </div>
                    </div>
                `;
            }

            form.innerHTML = `
                <div class="space-y-4">
                    <label class="flex items-center gap-3 cursor-pointer group">
                        <div class="relative">
                            <input type="checkbox" id="set-maint-mode" class="sr-only peer" ${settings.maintenance_mode ? 'checked' : ''}>
                            <div class="w-10 h-5 bg-slate-800 rounded-full peer peer-checked:bg-red-500 transition-all"></div>
                            <div class="absolute left-1 top-1 w-3 h-3 bg-white rounded-full peer-checked:translate-x-5 transition-all"></div>
                        </div>
                        <span class="text-sm font-bold text-slate-300 group-hover:text-white">Maintenance Mode</span>
                    </label>
                    <div class="space-y-2">
                        <p class="text-[10px] font-bold text-slate-500 uppercase">Maintenance Message</p>
                        <textarea id="set-maint-msg" class="w-full bg-slate-950 border border-white/5 rounded-xl p-3 text-xs text-white outline-none focus:ring-1 focus:ring-red-500/50 h-24">${settings.maintenance_message}</textarea>
                    </div>
                </div>
                <div class="space-y-4">
                     <label class="flex items-center gap-3 cursor-pointer group">
                        <div class="relative">
                            <input type="checkbox" id="set-signup-enabled" class="sr-only peer" ${settings.signup_enabled ? 'checked' : ''}>
                            <div class="w-10 h-5 bg-slate-800 rounded-full peer peer-checked:bg-primary-500 transition-all"></div>
                            <div class="absolute left-1 top-1 w-3 h-3 bg-white rounded-full peer-checked:translate-x-5 transition-all"></div>
                        </div>
                        <span class="text-sm font-bold text-slate-300 group-hover:text-white">Public Registration</span>
                    </label>
                    <div class="space-y-2">
                        <p class="text-[10px] font-bold text-slate-500 uppercase">Default Daily Limit</p>
                        <input type="number" id="set-daily-limit" value="${settings.default_daily_limit}" class="w-full bg-slate-950 border border-white/5 rounded-xl p-3 text-sm text-white font-mono outline-none focus:ring-1 focus:ring-primary-500">
                    </div>
                </div>
            `;

            // Load Audit Log
            const auditBody = document.getElementById('audit-log-body');
            const logs = await this.fetchSecure('/api/admin/audit_logs');
            if (auditBody) {
                auditBody.innerHTML = logs.logs.map(l => `
                    <tr>
                        <td class="py-2 font-bold text-white">${l.username}</td>
                        <td class="py-2"><span class="text-primary-400">${l.action}</span></td>
                        <td class="py-2 text-slate-500 truncate max-w-[150px]">${l.details}</td>
                        <td class="py-2 text-right text-slate-600">${new Date(l.timestamp).toLocaleTimeString()}</td>
                    </tr>
                `).join('') || '<tr><td colspan="4" class="py-4 text-center text-slate-700 italic">No recent system modifications</td></tr>';
            }

        } catch (err) {}
    },

    async loadNodes() {
         try {
            const queues = await this.fetchSecure('/api/admin/queues');
            const workers = await this.fetchSecure('/api/admin/workers');
            
            const qGrid = document.getElementById('queue-stats-grid');
            if (qGrid) {
                qGrid.innerHTML = Object.entries(queues.queues).map(([name, count]) => `
                    <div class="p-6 bg-slate-900/40 border border-white/5 rounded-2xl">
                        <p class="text-[10px] font-black text-slate-600 uppercase mb-2">${name}</p>
                        <p class="text-2xl font-black ${count > 100 ? 'text-red-500' : 'text-white'}" id="q-${name}">${count}</p>
                    </div>
                `).join('');
            }

            const wList = document.getElementById('workers-list');
            if (wList) {
                wList.innerHTML = Object.entries(workers.workers).map(([name, data]) => `
                    <div class="p-4 bg-white/5 border border-white/5 rounded-xl flex items-center justify-between">
                        <div>
                            <p class="text-xs font-bold text-white">${name.split('@')[0]}</p>
                            <p class="text-[9px] text-slate-500 font-mono">${data.length > 0 ? data.map(q => q.name).join(', ') : 'No active queues'}</p>
                        </div>
                        <div class="h-2 w-2 rounded-full bg-green-500 animate-pulse"></div>
                    </div>
                `).join('') || '<div class="col-span-2 text-center text-slate-700 uppercase tracking-widest text-[10px] py-12">No active processing nodes detected</div>';
            }
         } catch (err) {}
    },

    setupActions() {
        // Global Click Handler for delegation
        document.addEventListener('click', async (e) => {
            const target = e.target;
            
            // User Actions
            const upgradeBtn = target.closest('.action-upgrade');
            if (upgradeBtn) {
                if (confirm('Promote user to PREMIUM (30 days)?')) {
                    await this.fetchSecure(`/api/admin/users/${upgradeBtn.dataset.id}`, { method: 'PATCH', body: { is_paid: true } });
                    this.loadUsers();
                    this.showToast('User promoted to premium');
                }
            }

            const impersonateBtn = target.closest('.action-impersonate');
            if (impersonateBtn) {
                if (confirm('Impersonate this user?')) {
                    const res = await this.fetchSecure(`/api/admin/impersonate/${impersonateBtn.dataset.id}`, { method: 'POST' });
                    if (res) window.location.href = '/dashboard';
                }
            }

            const blockBtn = target.closest('.action-block');
            if (blockBtn) {
                const isBlocked = blockBtn.dataset.blocked === 'true';
                const action = isBlocked ? 'unblock' : 'block';
                if (confirm(`Are you sure you want to ${action} this user?`)) {
                    await this.fetchSecure(`/api/admin/users/${blockBtn.dataset.id}/${action}`, { method: 'POST' });
                    this.loadUsers();
                    this.showToast(`User ${action}ed`);
                }
            }

            const deleteBtn = target.closest('.action-delete');
            if (deleteBtn) {
                if (confirm('Permanently redact this user? (90-day recovery window)')) {
                    await this.fetchSecure(`/api/admin/users/${deleteBtn.dataset.id}`, { method: 'DELETE' });
                    this.loadUsers();
                    this.showToast('User redaction initiated');
                }
            }

            // DNS Verification
            const dnsBtn = target.closest('.btn-verify-dns');
            if (dnsBtn) {
                const origTxt = dnsBtn.innerText;
                dnsBtn.innerText = 'CHECKING...';
                dnsBtn.disabled = true;
                try {
                    const data = await this.fetchSecure('/api/admin/dns_check', { params: { domain: dnsBtn.dataset.email.split('@')[1] } });
                    const healthy = data.mx === 'configured' && data.spf === 'configured';
                    dnsBtn.className = `btn-verify-dns px-2 py-0.5 border rounded text-[8px] font-black tracking-widest uppercase transition-all ${healthy ? 'bg-green-500/10 text-green-400 border-green-500/10' : 'bg-red-500/10 text-red-400 border-red-500/10'}`;
                    dnsBtn.innerText = healthy ? 'HEALTHY' : 'ISSUES DETECTED';
                    dnsBtn.title = `MX: ${data.mx}, SPF: ${data.spf}, DMARC: ${data.dmarc}`;
                } catch (err) {
                    dnsBtn.innerText = 'ERROR';
                    dnsBtn.disabled = false;
                }
            }

            // Recruiter Actions
            const syncBtn = target.closest('#btn-sync-recruiters');
            if (syncBtn) {
                if (!confirm('Start industrial recruiter cloud sync?')) return;
                const origTxt = syncBtn.innerText;
                syncBtn.innerText = 'SYNCING...';
                syncBtn.disabled = true;
                try {
                    const data = await this.fetchSecure('/api/admin/recruiters/sync', { method: 'POST' });
                    if (data.ok) {
                        alert(`Sync Success: ${data.result.count} entries added.`);
                        this.loadRecruiters();
                    }
                } finally {
                    syncBtn.innerText = origTxt;
                    syncBtn.disabled = false;
                }
            }

            const refreshRecBtn = target.closest('#btn-refresh-recruiters');
            if (refreshRecBtn) {
                this.loadRecruiters();
                this.showToast('Recruiters refreshed');
            }

            // Deliverability & Trace
            const suppressBtn = target.closest('#btn-suppress');
            if (suppressBtn) {
                const email = document.getElementById('suppress-email')?.value;
                if (email && confirm(`Block ${email} globally?`)) {
                    await this.fetchSecure('/api/admin/suppression', { method: 'POST', body: { email, reason: 'admin_manual' } });
                    document.getElementById('suppress-email').value = '';
                    this.loadDeliverability();
                    this.showToast('Email suppressed');
                }
            }

            const traceBtn = target.closest('#btn-trace');
            if (traceBtn) {
                this.triggerTrace();
            }

            // Moderation
            const warnBtn = target.closest('.btn-warn-user');
            if (warnBtn) {
                 alert(`Warning system legacy. Contact ${warnBtn.dataset.username} at ${warnBtn.dataset.id}.`);
            }

            const banBtn = target.closest('.btn-ban-user');
            if (banBtn) {
                if (confirm(`CRITICAL: Hard ban user "${banBtn.dataset.username}"?`)) {
                    await this.fetchSecure(`/api/admin/users/${banBtn.dataset.id}/block`, { method: 'POST' });
                    this.loadModeration();
                    this.showToast('User restricted');
                }
            }

            // Infrastructure & Policy
            const optimizeBtn = target.closest('#btn-optimize-indexes');
            if (optimizeBtn) {
                if (confirm('Trigger full database index optimization?')) {
                    const res = await this.fetchSecure('/api/admin/optimize_indexes', { method: 'POST' });
                    if (res.ok) alert('Optimization propagated to cluster.');
                }
            }

            const broadcastBtn = target.closest('#btn-broadcast-notification');
            if (broadcastBtn) {
                const msg = prompt('Global Broadcast Message:');
                if (msg) {
                    await this.fetchSecure('/api/admin/broadcast', { method: 'POST', body: { message: msg } });
                    this.showToast('Broadcast sent');
                }
            }

            const clearBroadcastBtn = target.closest('#btn-clear-broadcast');
            if (clearBroadcastBtn) {
                await this.fetchSecure('/api/admin/broadcast', { method: 'DELETE' });
                this.showToast('Broadcast cleared');
            }

            const saveSettingsBtn = target.closest('#save-settings-btn');
            if (saveSettingsBtn) {
                const payload = {
                    maintenance_mode: document.getElementById('set-maint-mode').checked,
                    maintenance_message: document.getElementById('set-maint-msg').value,
                    signup_enabled: document.getElementById('set-signup-enabled').checked,
                    default_daily_limit: parseInt(document.getElementById('set-daily-limit').value)
                };
                await this.fetchSecure('/api/admin/settings', { method: 'POST', body: payload });
                this.loadPolicy();
                alert('System policies synchronized.');
            }

            const resetQueuesBtn = target.closest('#reset-queues-btn');
            if (resetQueuesBtn) {
                if (confirm('Emergency Sync will recalibrate daily counters. Proceed?')) {
                    await this.fetchSecure('/api/admin/queue/reset', { method: 'POST' });
                    this.showToast('Counters recalibrated');
                    this.loadNodes();
                }
            }

            const editRecBtn = target.closest('.btn-edit-recruiter');
            if (editRecBtn) {
                const modal = document.getElementById('modal-edit-recruiter');
                if (modal) {
                    document.getElementById('edit-recruiter-id').value = editRecBtn.dataset.id;
                    document.getElementById('edit-country').value = editRecBtn.dataset.country;
                    document.getElementById('edit-health').value = editRecBtn.dataset.health;
                    document.getElementById('edit-override').checked = editRecBtn.dataset.override === 'true';
                    
                    modal.classList.remove('hidden');
                    setTimeout(() => modal.classList.remove('opacity-0'), 10);
                }
            }

            if (target.id === 'btn-close-edit-modal') {
                const modal = document.getElementById('modal-edit-recruiter');
                modal.classList.add('opacity-0');
                setTimeout(() => modal.classList.add('hidden'), 300);
            }

            if (target.id === 'btn-save-edit') {
                const id = document.getElementById('edit-recruiter-id').value;
                const payload = {
                    detectedCountry: document.getElementById('edit-country').value,
                    health: document.getElementById('edit-health').value,
                    manual_override: document.getElementById('edit-override').checked
                };
                await this.fetchSecure(`/api/admin/recruiters/${id}`, { method: 'PATCH', body: payload });
                this.loadRecruiters();
                document.getElementById('btn-close-edit-modal').click();
                this.showToast('Recruiters record updated');
            }

            const refreshWorkersBtn = target.closest('#refresh-workers');
            if (refreshWorkersBtn) {
                this.loadNodes();
                this.showToast('Node heartbeats refreshed');
            }
        });
    },

    startActivityMonitor() {
        const body = document.getElementById('global-activity-body');
        if (!body) return;

        const updateActivity = async () => {
            try {
                const data = await this.fetchSecure('/api/admin/global_report');
                body.innerHTML = data.map(evt => `
                    <tr class="group">
                        <td class="py-3 font-mono text-slate-500">${new Date(evt.sent_at).toLocaleTimeString()}</td>
                        <td class="py-3 font-bold text-white">${evt.username}</td>
                        <td class="py-3">
                            <span class="px-2 py-0.5 rounded-full text-[9px] font-black uppercase tracking-widest ${this.getStatusColor(evt.status)}">
                                ${evt.status}
                            </span>
                        </td>
                        <td class="py-3 text-right text-slate-600 font-mono text-[10px]">${evt.ip_address}</td>
                    </tr>
                `).join('') || '<tr><td colspan="4" class="py-12 text-center text-slate-700 uppercase tracking-widest text-[10px] font-black">No incoming event stream matched</td></tr>';
            } catch (err) {}
        };

        updateActivity();
        setInterval(updateActivity, 15000);
    },

    getStatusColor(status) {
        if (!status) return 'bg-slate-500/10 text-slate-500';
        switch(status.toLowerCase()) {
            case 'sent': return 'bg-green-500/10 text-green-500 border border-green-500/20';
            case 'failed': return 'bg-red-500/10 text-red-500 border border-red-500/20';
            case 'skipped': return 'bg-slate-500/10 text-slate-500 border border-slate-500/20';
            case 'bounced': return 'bg-amber-500/10 text-amber-500 border border-amber-500/20';
            default: return 'bg-primary-500/10 text-primary-400 border border-primary-500/20';
        }
    },

    escape(str) {
        if (!str) return '';
        return str.replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
    },

    showToast(msg, type = 'success') {
        console.log(`[${type.toUpperCase()}] ${msg}`);
    }
};

document.addEventListener('DOMContentLoaded', () => AdminDashboard.init());
window.AdminDashboard = AdminDashboard;
