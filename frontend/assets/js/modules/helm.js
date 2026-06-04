/**
 * helm.js
 * =======
 * Modulo frontend per la Helm Application Console.
 * Gestisce tutte le interazioni con gli endpoint /api/v1/helm/*
 *
 * Struttura:
 *   - Releases   : loadReleases, viewReleaseStatus, viewReleaseHistory,
 *                  viewReleaseValues, confirmUninstall, confirmRollback
 *   - Deploy     : showChartSearch, installChart, showZipUpload, deployFromZip
 *   - Repos      : loadRepositories, showAddRepoForm, submitAddRepo, updateRepos
 *   - Helpers UI : renderHelmStatus, renderRevisionBadge, _helmPost, _helmDelete
 */

// ---------------------------------------------------------------------------
// HELPER BASE: chiamate verso gli endpoint /helm/* e /repos/*
// Il prefisso è /api/v1 come per le altre route (definito in api.js)
// ---------------------------------------------------------------------------

const HELM_BASE = "";   // relativo: apiCall gestisce già il prefisso API_BASE

/**
 * Wrapper per POST verso endpoint helm con body JSON opzionale.
 * Costruisce la query string per i parametri di install/upgrade.
 */
async function _helmPost(path, queryParams = {}, jsonBody = null) {
    const qs = new URLSearchParams(
        Object.fromEntries(Object.entries(queryParams).filter(([, v]) => v !== null && v !== undefined && v !== ""))
    ).toString();
    const url = qs ? `${path}?${qs}` : path;
    return apiCall(url, "POST", false, jsonBody || undefined);
}

async function _helmDelete(path, queryParams = {}) {
    const qs = new URLSearchParams(
        Object.fromEntries(Object.entries(queryParams).filter(([, v]) => v !== null && v !== undefined))
    ).toString();
    const url = qs ? `${path}?${qs}` : path;
    return apiCall(url, "DELETE");
}


// ---------------------------------------------------------------------------
// BADGES & STATUS RENDERERS
// ---------------------------------------------------------------------------

function renderHelmStatus(status) {
    const s = (status || "").toLowerCase();
    const map = {
        deployed:   { cls: "status-running",  label: "deployed"   },
        failed:     { cls: "status-failed",   label: "failed"     },
        pending:    { cls: "status-pending",  label: "pending"    },
        superseded: { cls: "status-stopped",  label: "superseded" },
        uninstalled:{ cls: "status-stopped",  label: "uninstalled"},
        uninstalling:{ cls:"status-pending",  label: "uninstalling"},
    };
    const m = map[s] || { cls: "status-pending", label: status || "unknown" };
    return `<span class="badge ${m.cls}">${m.label}</span>`;
}

function renderRevisionBadge(rev) {
    return `<span style="
        display:inline-block; padding:2px 10px;
        border-radius:12px; font-size:0.72rem; font-weight:700;
        background:#f1f5f9; color:#475569; border:1px solid #e2e8f0;
    ">rev. ${rev}</span>`;
}

function _helmSpinner() {
    return '<div style="text-align:center; padding:40px;"><i class="fas fa-spinner fa-spin fa-2x" style="color:var(--accent)"></i></div>';
}

function _helmEmpty(msg) {
    return `<p style="text-align:center; margin-top:30px; color:var(--text-muted); font-size:0.9rem;">${msg}</p>`;
}

function _renderResultBox(result, successMsg = null) {
    if (!result) return '';
    const ok = result.success;
    const msg = successMsg || result.stdout || result.stderr || (ok ? "Operation completed." : "Operation failed.");
    const color = ok ? "var(--accent)" : "#ef4444";
    const icon  = ok ? "fa-check-circle" : "fa-times-circle";
    return `
        <div style="margin-top:16px; padding:14px 16px; border-radius:10px;
                    border-left:4px solid ${color}; background:${ok ? "rgba(59,130,246,0.05)" : "#fff5f5"};">
            <div style="display:flex; align-items:center; gap:8px; margin-bottom:${result.stderr && !ok ? '8px' : '0'}">
                <i class="fas ${icon}" style="color:${color}; font-size:1rem;"></i>
                <span style="font-size:0.85rem; color:#1e293b; font-weight:500;">${msg}</span>
            </div>
            ${result.stderr && !ok ? `<pre style="margin:0; font-size:0.75rem; color:#ef4444; white-space:pre-wrap;">${result.stderr}</pre>` : ""}
        </div>`;
}

// ---------------------------------------------------------------------------
// NAMESPACE SELECTOR (riutilizzato dalla helm page)
// ---------------------------------------------------------------------------

async function loadNamespaceList() {
    const container = document.getElementById('nsContextArea');
    if (!container) return;
    try {
        const data = await apiCall('/namespaces');
        const namespaces = data.items || [];

        if (!data.can_list || namespaces.length === 0) {
            showManualInput();
            return;
        }

        let selectHtml = `<select id="nsSelect" onchange="updateNamespaceContext(this.value)"
            style="padding:8px 12px; border-radius:8px; border:1px solid var(--border);
                   font-size:0.82rem; background:#fff; cursor:pointer; min-width:180px;">`;
        namespaces.forEach(ns => {
            const sel = ns.name === window.currentNamespace ? 'selected' : '';
            selectHtml += `<option value="${ns.name}" ${sel}>${ns.name}</option>`;
        });
        selectHtml += `</select>`;
        container.innerHTML = selectHtml;
    } catch (err) {
        showManualInput();
    }
}


// ---------------------------------------------------------------------------
// RELEASES — lista principale
// ---------------------------------------------------------------------------

async function loadReleases() {
    window.currentView = 'releases';
    const ns = window.currentNamespace;
    const resArea = document.getElementById('resultArea');
    resArea.innerHTML = _helmSpinner();

    try {
        const result = await apiCall(`/helm/namespaces/${ns}/releases`);
        const releases = result.data || [];

        if (releases.length === 0) {
            resArea.innerHTML = `
                <h2>Installed Releases [${ns}]</h2>
                ${_helmEmpty("No Helm releases found in this namespace.")}`;
            return;
        }

        let html = `
            <h2>Installed Releases [${ns}]</h2>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Release</th>
                        <th>Chart</th>
                        <th>App Version</th>
                        <th>Revision</th>
                        <th>Updated</th>
                        <th>Status</th>
                        <th style="text-align:right">Actions</th>
                    </tr>
                </thead>
                <tbody>`;

        releases.forEach(r => {
            const updated = r.updated ? r.updated.substring(0, 16).replace("T", " ") : "N/A";
            html += `
                <tr>
                    <td><b>${r.name}</b></td>
                    <td><code style="font-size:0.78rem">${r.chart}</code></td>
                    <td><span style="color:var(--text-muted); font-size:0.82rem">${r.app_version || "—"}</span></td>
                    <td>${renderRevisionBadge(r.revision)}</td>
                    <td><small style="color:var(--text-muted)">${updated}</small></td>
                    <td>${renderHelmStatus(r.status)}</td>
                    <td style="text-align:right; white-space:nowrap;">
                        <button onclick="viewReleaseStatus('${r.name}')" class="btn-small table-btn" title="Status / Manifest"><i class="fas fa-info-circle"></i></button>
                        <button onclick="viewReleaseHistory('${r.name}')" class="btn-small table-btn" title="History"><i class="fas fa-history"></i></button>
                        <button onclick="viewReleaseValues('${r.name}')" class="btn-small table-btn" title="Values"><i class="fas fa-sliders-h"></i></button>
                        <button onclick="confirmUninstall('${r.name}')" class="btn-small delete-btn" title="Uninstall"><i class="fas fa-trash"></i></button>
                    </td>
                </tr>`;
        });

        resArea.innerHTML = html + '</tbody></table>';

    } catch (err) {
        if (err.message === "RESTRICTED") renderRestrictedAccess();
        else showError(err.message);
    }
}


// ---------------------------------------------------------------------------
// RELEASES — status detail (inline expand)
// ---------------------------------------------------------------------------

async function viewReleaseStatus(name) {
    const rows = document.querySelectorAll(`#status-detail-${name}`);
    rows.forEach(r => r.remove());

    const allRows = Array.from(document.querySelectorAll('table.data-table tbody tr'));
    const targetRow = allRows.find(tr => tr.querySelector('td b')?.textContent === name);
    if (!targetRow) return;

    targetRow.insertAdjacentHTML('afterend', `
        <tr id="status-detail-${name}">
            <td colspan="7">
                <div style="padding:14px; background:#f8fafc; border-radius:8px; margin:4px 0;">
                    <i class="fas fa-spinner fa-spin"></i> Loading status...
                </div>
            </td>
        </tr>`);

    try {
        const ns = window.currentNamespace;
        const result = await apiCall(`/helm/namespaces/${ns}/releases/${name}/status`);
        const data = result.data || {};
        const info = data.info || {};

        const firstDeployed = info.first_deployed ? info.first_deployed.substring(0,16).replace("T"," ") : "—";
        const lastDeployed  = info.last_deployed  ? info.last_deployed.substring(0,16).replace("T"," ")  : "—";

        document.getElementById(`status-detail-${name}`).innerHTML = `
            <td colspan="7">
                <div style="padding:16px; background:#f8fafc; border-radius:8px; margin:4px 0; border:1px solid var(--border);">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                        <b style="font-size:0.95rem;">Release Detail: ${name}</b>
                        <button onclick="document.getElementById('status-detail-${name}').remove()"
                                style="background:none; border:none; color:var(--text-muted); cursor:pointer; font-size:1.1rem;">&times;</button>
                    </div>
                    <div style="display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-bottom:14px;">
                        <div><small style="color:var(--text-muted); font-size:0.7rem; text-transform:uppercase;">Status</small><br>${renderHelmStatus(info.status)}</div>
                        <div><small style="color:var(--text-muted); font-size:0.7rem; text-transform:uppercase;">First Deployed</small><br><span style="font-size:0.83rem">${firstDeployed}</span></div>
                        <div><small style="color:var(--text-muted); font-size:0.7rem; text-transform:uppercase;">Last Deployed</small><br><span style="font-size:0.83rem">${lastDeployed}</span></div>
                    </div>
                    ${info.notes ? `
                    <div style="margin-bottom:12px;">
                        <small style="color:var(--text-muted); font-size:0.7rem; text-transform:uppercase; display:block; margin-bottom:4px;">Notes</small>
                        <pre style="margin:0; font-size:0.78rem; background:#fff; border:1px solid var(--border); border-radius:6px; padding:10px; white-space:pre-wrap; color:#334155;">${info.notes}</pre>
                    </div>` : ""}
                    ${data.manifest ? `
                    <details style="margin-top:8px;">
                        <summary style="cursor:pointer; font-size:0.82rem; color:var(--accent); font-weight:600;">View Manifest YAML</summary>
                        <pre style="margin-top:8px; font-size:0.73rem; background:#1e293b; color:#e2e8f0; border-radius:8px; padding:14px; overflow-x:auto; max-height:320px; white-space:pre-wrap;">${data.manifest}</pre>
                    </details>` : ""}
                </div>
            </td>`;

    } catch (err) {
        document.getElementById(`status-detail-${name}`).innerHTML = `
            <td colspan="7"><div style="padding:12px; color:#ef4444; font-size:0.85rem;">Error: ${err.message}</div></td>`;
    }
}


// ---------------------------------------------------------------------------
// RELEASES — history
// ---------------------------------------------------------------------------

async function viewReleaseHistory(name) {
    const rows = document.querySelectorAll(`#history-detail-${name}`);
    rows.forEach(r => r.remove());

    const allRows = Array.from(document.querySelectorAll('table.data-table tbody tr'));
    const targetRow = allRows.find(tr => tr.querySelector('td b')?.textContent === name);
    if (!targetRow) return;

    targetRow.insertAdjacentHTML('afterend', `
        <tr id="history-detail-${name}">
            <td colspan="7"><div style="padding:14px;"><i class="fas fa-spinner fa-spin"></i> Loading history...</div></td>
        </tr>`);

    try {
        const ns = window.currentNamespace;
        const result = await apiCall(`/helm/namespaces/${ns}/releases/${name}/history`);
        const history = result.data || [];

        let histHtml = `
            <div style="padding:16px; background:#f8fafc; border-radius:8px; border:1px solid var(--border);">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                    <b style="font-size:0.95rem;">Revision History: ${name}</b>
                    <button onclick="document.getElementById('history-detail-${name}').remove()"
                            style="background:none; border:none; color:var(--text-muted); cursor:pointer; font-size:1.1rem;">&times;</button>
                </div>
                <table style="width:100%; border-collapse:collapse; font-size:0.82rem;">
                    <thead>
                        <tr style="border-bottom:1px solid var(--border);">
                            <th style="padding:6px 10px; text-align:left; color:var(--text-muted); font-weight:600;">Rev</th>
                            <th style="padding:6px 10px; text-align:left; color:var(--text-muted); font-weight:600;">Chart</th>
                            <th style="padding:6px 10px; text-align:left; color:var(--text-muted); font-weight:600;">Updated</th>
                            <th style="padding:6px 10px; text-align:left; color:var(--text-muted); font-weight:600;">Status</th>
                            <th style="padding:6px 10px; text-align:left; color:var(--text-muted); font-weight:600;">Description</th>
                            <th style="padding:6px 10px; text-align:right;"></th>
                        </tr>
                    </thead>
                    <tbody>`;

        history.forEach(h => {
            const updated = h.updated ? h.updated.substring(0,16).replace("T"," ") : "—";
            histHtml += `
                <tr style="border-bottom:1px solid #f1f5f9;">
                    <td style="padding:7px 10px;">${renderRevisionBadge(h.revision)}</td>
                    <td style="padding:7px 10px;"><code style="font-size:0.75rem">${h.chart}</code></td>
                    <td style="padding:7px 10px; color:var(--text-muted)">${updated}</td>
                    <td style="padding:7px 10px;">${renderHelmStatus(h.status)}</td>
                    <td style="padding:7px 10px; color:#64748b; font-size:0.78rem;">${h.description || "—"}</td>
                    <td style="padding:7px 10px; text-align:right;">
                        <button onclick="confirmRollback('${name}', ${h.revision})"
                                class="btn-small restart-btn" title="Rollback to this revision">
                            <i class="fas fa-undo"></i>
                        </button>
                    </td>
                </tr>`;
        });

        histHtml += `</tbody></table></div>`;

        document.getElementById(`history-detail-${name}`).innerHTML = `<td colspan="7">${histHtml}</td>`;

    } catch (err) {
        document.getElementById(`history-detail-${name}`).innerHTML = `
            <td colspan="7"><div style="padding:12px; color:#ef4444; font-size:0.85rem;">Error: ${err.message}</div></td>`;
    }
}


// ---------------------------------------------------------------------------
// RELEASES — values
// ---------------------------------------------------------------------------

async function viewReleaseValues(name) {
    const rows = document.querySelectorAll(`#values-detail-${name}`);
    rows.forEach(r => r.remove());

    const allRows = Array.from(document.querySelectorAll('table.data-table tbody tr'));
    const targetRow = allRows.find(tr => tr.querySelector('td b')?.textContent === name);
    if (!targetRow) return;

    targetRow.insertAdjacentHTML('afterend', `
        <tr id="values-detail-${name}">
            <td colspan="7"><div style="padding:14px;"><i class="fas fa-spinner fa-spin"></i> Loading values...</div></td>
        </tr>`);

    try {
        const ns = window.currentNamespace;
        const result = await apiCall(`/helm/namespaces/${ns}/releases/${name}/values`);
        const values = result.data || {};

        const valuesYaml = Object.keys(values).length > 0
            ? JSON.stringify(values, null, 2)
            : "(no override values — using chart defaults)";

        document.getElementById(`values-detail-${name}`).innerHTML = `
            <td colspan="7">
                <div style="padding:16px; background:#f8fafc; border-radius:8px; border:1px solid var(--border);">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                        <b style="font-size:0.95rem;">Applied Values: ${name}</b>
                        <button onclick="document.getElementById('values-detail-${name}').remove()"
                                style="background:none; border:none; color:var(--text-muted); cursor:pointer; font-size:1.1rem;">&times;</button>
                    </div>
                    <pre style="font-size:0.78rem; background:#1e293b; color:#e2e8f0; border-radius:8px;
                                padding:14px; overflow-x:auto; max-height:280px; white-space:pre-wrap; margin:0;">${valuesYaml}</pre>
                </div>
            </td>`;

    } catch (err) {
        document.getElementById(`values-detail-${name}`).innerHTML = `
            <td colspan="7"><div style="padding:12px; color:#ef4444; font-size:0.85rem;">Error: ${err.message}</div></td>`;
    }
}


// ---------------------------------------------------------------------------
// RELEASES — uninstall
// ---------------------------------------------------------------------------

async function confirmUninstall(name) {
    // 1. Chiediamo conferma con il nuovo modal professionale
    const confirmed = await showConfirm(
        "Uninstall Helm Release", 
        `Are you sure you want to uninstall the release <strong>${name}</strong>?<br>This will remove all managed resources in <strong>${window.currentNamespace}</strong>.`,
        true 
    );
    if (!confirmed) return;

    // 2. Scelta sulla History (BLU/NEUTRO)
    // Non è un'azione pericolosa, quindi isDanger = false
    const keepHistory = await showConfirm(
        "Keep History?", 
        "Do you want to <strong>keep the release history</strong>? Keeping history allows you to rollback to this version later.",
        false 
    );

    try {
        const ns = window.currentNamespace;
        const result = await _helmDelete(`/helm/namespaces/${ns}/releases/${name}`, { keep_history: keepHistory });
        showSuccess(`Release "${name}" successfully uninstalled.`);
        loadReleases();
    } catch (err) {
        showError(err.message);
    }
}


// ---------------------------------------------------------------------------
// RELEASES — rollback
// ---------------------------------------------------------------------------

async function confirmRollback(name, revision) {
    const confirmed = await showConfirm(
        "Confirm Rollback", 
        `Rollback release ${name} to revision ${revision}?`,
        true // Imposta il tasto rosso per azioni pericolose
    );
    if (!confirmed) return;

    try {
        const ns = window.currentNamespace;
        const result = await _helmPost(`/helm/namespaces/${ns}/releases/${name}/rollback`, { revision });

        // Chiudi la riga di history e ricarica
        const histRow = document.getElementById(`history-detail-${name}`);
        if (histRow) histRow.remove();

        const resultBox = _renderResultBox(result, `Rollback to revision ${revision} completed.`);
        document.querySelector('table.data-table')?.insertAdjacentHTML('afterend', resultBox);

        setTimeout(() => loadReleases(), 1500);

    } catch (err) {
        showError(err.message);
    }
}


// ---------------------------------------------------------------------------
// CATALOG — search charts
// ---------------------------------------------------------------------------

function showChartSearch() {
    window.currentView = 'search';
    const resArea = document.getElementById('resultArea');
    document.getElementById('controlsContainer').style.display = 'none';

    resArea.innerHTML = `
        <div class="deploy-container">
            <h2>Search Charts</h2>
            <div class="info-note" style="background:rgba(var(--accent-rgb),0.08); border-left:4px solid var(--accent);
                 padding:12px 14px; border-radius:6px; margin-bottom:20px; font-size:0.85rem; line-height:1.5; color:var(--text-secondary);">
                <i class="fas fa-info-circle" style="color:var(--accent); margin-right:8px;"></i>
                Search across all configured Helm repositories. Add repositories first if needed.
            </div>

            <div style="display:flex; gap:10px; margin-bottom:24px;">
                <input type="text" id="chartSearchInput" placeholder="e.g. nginx, bitnami/redis, prometheus..."
                    style="flex:1; padding:10px 14px; border-radius:8px; border:1px solid var(--border); font-size:0.88rem;"
                    onkeydown="if(event.key==='Enter') executeChartSearch()">
                <button onclick="executeChartSearch()" class="btn-action">
                    <i class="fas fa-search"></i> Search
                </button>
            </div>

            <div id="chartSearchResults"></div>
        </div>`;
}

async function executeChartSearch() {
    const q = document.getElementById('chartSearchInput')?.value?.trim();
    if (!q) return;

    const resultsDiv = document.getElementById('chartSearchResults');
    resultsDiv.innerHTML = _helmSpinner();

    try {
        const result = await apiCall(`/helm/charts/search?q=${encodeURIComponent(q)}`);
        const charts = result.data || [];

        if (charts.length === 0) {
            resultsDiv.innerHTML = _helmEmpty(`No charts found for "${q}". Try adding the repository first.`);
            return;
        }

        let html = `
            <table class="data-table">
                <thead>
                    <tr>
                        <th style="width: 25%;">Chart</th>
                        <th style="width: 10%;">Version</th>
                        <th style="width: 10%;">App</th>
                        <th style="width: 40%;">Description</th>
                        <th style="width: 15%; text-align:right">Actions</th>
                    </tr>
                </thead>
                <tbody>`;

        charts.forEach(c => {
            const safeName = encodeURIComponent(c.name);
            const safeVer  = encodeURIComponent(c.version || "");
            
            // Tronchiamo il nome se è un URL lunghissimo per non rompere il layout
            const displayName = c.name.length > 40 ? c.name.substring(0, 37) + '...' : c.name;

            html += `
                <tr>
                    <td title="${c.name}"><b>${displayName}</b></td>
                    <td><code style="font-size:0.75rem">${c.version || "—"}</code></td>
                    <td><span style="font-size:0.75rem">${c.app_version || "—"}</span></td>
                    <td title="${c.description}" style="font-size:0.8rem; color:#475569;">
                        ${c.description || "—"}
                    </td>
                    <td style="text-align:right; white-space:nowrap;">
                        <button onclick="showInstallForm('${c.name}', '${c.version || ''}')" 
                                class="btn-small table-btn">
                            <i class="fas fa-rocket"></i>
                        </button>
                        <button onclick="previewChartValues('${safeName}', '${safeVer}')" 
                                class="btn-small table-btn">
                            <i class="fas fa-eye"></i>
                        </button>
                    </td>
                </tr>`;
        });


        resultsDiv.innerHTML = html + '</tbody></table>';

    } catch (err) {
        if (err.message === "RESTRICTED") renderRestrictedAccess();
        else resultsDiv.innerHTML = `<p style="color:#ef4444; font-size:0.85rem;">Error: ${err.message}</p>`;
    }
}

async function previewChartValues(chartRefEncoded, versionEncoded) {
    const chartRef = decodeURIComponent(chartRefEncoded);
    const version  = decodeURIComponent(versionEncoded);

    const existing = document.getElementById('chart-values-preview');
    if (existing) existing.remove();

    const resultsDiv = document.getElementById('chartSearchResults');
    resultsDiv.insertAdjacentHTML('beforeend', `
        <div id="chart-values-preview" style="margin-top:20px; padding:16px; background:#f8fafc;
             border-radius:10px; border:1px solid var(--border);">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                <b style="font-size:0.9rem;">Default Values: ${chartRef}</b>
                <button onclick="document.getElementById('chart-values-preview').remove()"
                        style="background:none; border:none; color:var(--text-muted); cursor:pointer; font-size:1.1rem;">&times;</button>
            </div>
            <div id="chart-values-content">${_helmSpinner()}</div>
        </div>`);

    try {
        const qs = version ? `?chart_ref=${encodeURIComponent(chartRef)}&version=${encodeURIComponent(version)}` : `?chart_ref=${encodeURIComponent(chartRef)}`;
        const result = await apiCall(`/helm/charts/values${qs}`);

        document.getElementById('chart-values-content').innerHTML = `
            <pre style="font-size:0.75rem; background:#1e293b; color:#e2e8f0; border-radius:8px;
                        padding:14px; overflow-x:auto; max-height:300px; white-space:pre-wrap; margin:0;">${result.stdout || "(empty)"}</pre>`;

    } catch (err) {
        document.getElementById('chart-values-content').innerHTML =
            `<p style="color:#ef4444; font-size:0.85rem;">Error: ${err.message}</p>`;
    }
}


// ---------------------------------------------------------------------------
// CATALOG — install form (inline sotto la search)
// ---------------------------------------------------------------------------

function showInstallForm(chartRef, version) {
    const existing = document.getElementById('install-form-panel');
    if (existing) existing.remove();

    const resultsDiv = document.getElementById('chartSearchResults');
    resultsDiv.insertAdjacentHTML('beforeend', `
        <div id="install-form-panel" style="margin-top:20px; padding:20px; background:#f8fafc;
             border-radius:10px; border:1px solid var(--border);">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
                <b style="font-size:0.95rem;"><i class="fas fa-rocket" style="color:var(--accent); margin-right:8px;"></i>Deploy: ${chartRef}</b>
                <button onclick="document.getElementById('install-form-panel').remove()"
                        style="background:none; border:none; color:var(--text-muted); cursor:pointer; font-size:1.1rem;">&times;</button>
            </div>

            <div style="display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-bottom:14px;">
                <div>
                    <label style="font-size:0.72rem; font-weight:600; color:var(--text-muted); text-transform:uppercase; display:block; margin-bottom:5px;">Release Name *</label>
                    <input type="text" id="inst_release_name" placeholder="my-release"
                        style="width:100%; padding:9px 12px; border-radius:8px; border:1px solid var(--border); font-size:0.85rem; box-sizing:border-box;">
                </div>
                <div>
                    <label style="font-size:0.72rem; font-weight:600; color:var(--text-muted); text-transform:uppercase; display:block; margin-bottom:5px;">Namespace</label>
                    <input type="text" id="inst_namespace" value="${window.currentNamespace}"
                        style="width:100%; padding:9px 12px; border-radius:8px; border:1px solid var(--border); font-size:0.85rem; box-sizing:border-box;">
                </div>
                <div>
                    <label style="font-size:0.72rem; font-weight:600; color:var(--text-muted); text-transform:uppercase; display:block; margin-bottom:5px;">Version</label>
                    <input type="text" id="inst_version" value="${version}" placeholder="latest"
                        style="width:100%; padding:9px 12px; border-radius:8px; border:1px solid var(--border); font-size:0.85rem; box-sizing:border-box;">
                </div>
                <div style="display:flex; align-items:end; gap:20px; padding-bottom:2px;">
                    <label style="display:flex; align-items:center; gap:7px; font-size:0.82rem; cursor:pointer;">
                        <input type="checkbox" id="inst_atomic" style="width:15px; height:15px;">
                        Atomic (auto-rollback)
                    </label>
                    <label style="display:flex; align-items:center; gap:7px; font-size:0.82rem; cursor:pointer;">
                        <input type="checkbox" id="inst_wait" style="width:15px; height:15px;">
                        Wait for ready
                    </label>
                    <label style="display:flex; align-items:center; gap:7px; font-size:0.82rem; cursor:pointer; color:var(--accent); font-weight:600;">
                        <input type="checkbox" id="inst_dry_run" style="width:15px; height:15px;">
                        Simulate (Dry-Run)
                    </label>
                </div>
            </div>

            <label style="font-size:0.72rem; font-weight:600; color:var(--text-muted); text-transform:uppercase; display:block; margin-bottom:5px;">
                Values Override (JSON)
                <span style="font-weight:400; font-size:0.7rem; text-transform:none; margin-left:8px; color:#94a3b8">optional — override chart defaults</span>
            </label>
            <textarea id="inst_values" rows="5" placeholder='{ "replicaCount": 2, "image": { "tag": "latest" } }'
                style="width:100%; padding:10px; border-radius:8px; border:1px solid var(--border);
                       font-family:monospace; font-size:0.8rem; box-sizing:border-box;"></textarea>

            <div style="display:flex; gap:10px; margin-top:14px;">
                <button onclick="lintChart('${chartRef}', '${version}')" 
                                class="btn-small table-btn">
                    <i class="fas fa-stethoscope"></i>
                </button>
                <button onclick="executeInstall('${chartRef}')" class="btn-action" style="flex:1;">
                    <i class="fas fa-paper-plane"></i> Deploy Chart
                </button>
            </div>
            <div id="install-result"></div>
        </div>`);
}

async function executeInstall(chartRef) {
    const releaseName = document.getElementById('inst_release_name')?.value?.trim();
    const namespace   = document.getElementById('inst_namespace')?.value?.trim() || window.currentNamespace;
    const version     = document.getElementById('inst_version')?.value?.trim() || null;
    const atomic      = document.getElementById('inst_atomic')?.checked;
    const wait        = document.getElementById('inst_wait')?.checked;
    const dryRun      = document.getElementById('inst_dry_run')?.checked;
    const valuesRaw   = document.getElementById('inst_values')?.value?.trim();

    if (!releaseName) { showError("Release name is required."); return; }

    let values = null;
    if (valuesRaw) {
        try { values = JSON.parse(valuesRaw); }
        catch { showError("Invalid JSON in Values Override field."); return; }
    }

    const btn = document.querySelector('#install-form-panel .btn-action');
    btn.disabled = true;
    // Feedback visivo diverso per la simulazione
    btn.innerHTML = dryRun 
        ? '<i class="fas fa-spinner fa-spin"></i> Simulating...' 
        : '<i class="fas fa-spinner fa-spin"></i> Deploying...';

    try {
        const params = { chart_ref: chartRef, create_namespace: true, atomic, wait, dry_run: dryRun };
        if (version) params.version = version;

        const result = await _helmPost(
            `/helm/namespaces/${namespace}/releases/${releaseName}`,
            params,
            values
        );

        if (dryRun && result.success) {
            // Estrae il manifest generato da Helm e lo mostra in un blocco di codice
            const manifestYaml = result.data?.manifest || "(No manifest generated)";
            document.getElementById('install-result').innerHTML = `
                <div style="margin-top:16px; padding:16px; background:#f8fafc; border-radius:10px; border:1px solid var(--accent);">
                    <div style="display:flex; align-items:center; gap:8px; margin-bottom:10px;">
                        <i class="fas fa-flask" style="color:var(--accent);"></i>
                        <b style="font-size:0.9rem; color:var(--accent);">Simulation Success (Dry-Run)</b>
                    </div>
                    <pre style="font-size:0.75rem; background:#1e293b; color:#e2e8f0; border-radius:8px; padding:14px; overflow-x:auto; max-height:400px; white-space:pre-wrap; margin:0;">${manifestYaml}</pre>
                </div>
            `;
        } else {
            // Comportamento standard per il deploy reale
            document.getElementById('install-result').innerHTML =
                _renderResultBox(result, `Release "${releaseName}" deployed successfully.`);

            if (result.success) setTimeout(() => loadReleases(), 2000);
        }

    } catch (err) {
        document.getElementById('install-result').innerHTML =
            _renderResultBox({ success: false, stderr: err.message });
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-paper-plane"></i> Deploy Chart';
    }
}


// ---------------------------------------------------------------------------
// REPOSITORIES
// ---------------------------------------------------------------------------

async function loadRepositories() {
    window.currentView = 'repos';
    const resArea = document.getElementById('resultArea');
    document.getElementById('controlsContainer').style.display = 'none';
    resArea.innerHTML = _helmSpinner();

    try {
        const result = await apiCall('/helm/repos');
        const repos = result.data || [];

        let html = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
                <h2 class="page-title"">Helm Repositories</h2>
                <div style="display:flex; gap:10px;">
                    <button onclick="updateRepos()" class="btn-action" id="btnUpdateRepos" title="helm repo update">
                        <i class="fas fa-sync"></i> Update All
                    </button>
                    <button onclick="showAddRepoForm()" class="btn-action">
                        <i class="fas fa-plus"></i> Add Repository
                    </button>
                </div>
            </div>
            <div id="repo-action-result"></div>`;

        if (repos.length === 0) {
            html += _helmEmpty("No repositories configured.");
        } else {
            html += `
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>URL</th>
                            <th style="text-align:right">Actions</th>
                        </tr>
                    </thead>
                    <tbody>`;

            repos.forEach(r => {
                html += `
                    <tr>
                        <td><b>${r.name}</b></td>
                        <td><code style="font-size:0.78rem;">${r.url}</code></td>
                        <td style="text-align:right; white-space:nowrap;">
                            <button onclick="updateRepos('${r.name}')" class="btn-small table-btn" title="Update only this repo" style="margin-right:5px;">
                                <i class="fas fa-sync-alt"></i>
                            </button>
                            <button onclick="searchInRepo('${r.name}')" class="btn-small table-btn" title="Search charts in this repo">
                                <i class="fas fa-search"></i>
                            </button>
                        </td>
                    </tr>`;
            });
            html += '</tbody></table>';
        }
        html += '<div id="add-repo-panel"></div>';
        resArea.innerHTML = html;
    } catch (err) {
        showError(err.message);
    }
}

function showAddRepoForm() {
    const panel = document.getElementById('add-repo-panel');
    if (!panel) return;

    panel.innerHTML = `
        <div class="repo-form-card">
            <div class="repo-form-header">
                <i class="fas fa-database"></i>
                <h3 style="margin:0; font-size:1.1rem; color:var(--text-main);">Add New Repository</h3>
            </div>

            <div style="display:grid; grid-template-columns: 1fr 2fr; gap:15px; margin-bottom: 5px;">
                <div class="form-group">
                    <label class="label-small" style="margin-left:12px;">Local Name</label>
                    <input type="text" id="repo_name" placeholder="e.g. gitlab-charts" class="input-modern">
                    <small style="color:var(--text-muted); font-size:0.65rem; margin-left:12px; display:block; margin-top:4px;">Identifier for your cluster</small>
                </div>
                <div class="form-group">
                    <label class="label-small" style="margin-left:12px;">Repository URL</label>
                    <input type="text" id="repo_url" placeholder="https://gitlab.io/my-repo" class="input-modern">
                    <small style="color:var(--text-muted); font-size:0.65rem; margin-left:12px; display:block; margin-top:4px;">Official URL of the Helm index</small>
                </div>
            </div>

            <div class="auth-switch-container">
                <label style="display:flex; align-items:center; justify-content:space-between; cursor:pointer; margin:0;">
                    <div style="display:flex; align-items:center; gap:10px;">
                        <i class="fas fa-shield-alt" id="auth_icon" style="color:#94a3b8; transition: color 0.3s;"></i>
                        <span style="font-size:0.85rem; font-weight:600; color:var(--text-main);">Private Repository (Auth)</span>
                    </div>
                    <input type="checkbox" id="auth_toggle" onchange="toggleAuthFields(this.checked)" 
                           style="width:18px; height:18px; cursor:pointer; accent-color:var(--accent);">
                </label>
                
                <div id="auth_fields" style="max-height: 0; opacity: 0; overflow: hidden; transition: all 0.3s ease-in-out; display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
                    <div style="padding-top:15px;">
                        <label class="label-small" style="margin-left:12px;">Username</label>
                        <input type="text" id="repo_user" placeholder="gitlab-token" class="input-modern">
                    </div>
                    <div style="padding-top:15px;">
                        <label class="label-small" style="margin-left:12px;">Access Token</label>
                        <input type="password" id="repo_pass" placeholder="••••••••" class="input-modern">
                    </div>
                </div>
            </div>

            <div style="display:flex; justify-content: flex-end; gap:12px; margin-top:10px;">
                <button onclick="document.getElementById('add-repo-panel').innerHTML=''" class="btn-modal-cancel">
                    Cancel
                </button>
                <button onclick="submitAddRepo()" class="btn-modal-primary">
                    <i class="fas fa-save" style="margin-right:8px;"></i> Save Repository
                </button>
            </div>
            
            <div id="add-repo-result" style="margin-top:15px;"></div>
        </div>`;
    
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/**
 * Gestisce l'animazione e lo stile dei campi autenticazione
 */
function toggleAuthFields(show) {
    const fields = document.getElementById('auth_fields');
    const icon = document.getElementById('auth_icon');
    
    if (show) {
        fields.style.maxHeight = '150px'; // Ridotto per essere più compatto
        fields.style.opacity = '1';
        fields.style.marginTop = '5px';
        if(icon) icon.style.color = 'var(--accent)';
    } else {
        fields.style.maxHeight = '0';
        fields.style.opacity = '0';
        fields.style.marginTop = '0';
        if(icon) icon.style.color = '#94a3b8';
    }
}

async function submitAddRepo() {
    const name = document.getElementById('repo_name')?.value?.trim();
    const url  = document.getElementById('repo_url')?.value?.trim();
    const useAuth = document.getElementById('auth_toggle').checked;
    
    if (!name || !url) { showError("Both name and URL are required."); return; }

    let queryParams = `?name=${encodeURIComponent(name)}&url=${encodeURIComponent(url)}`;
    
    if (useAuth) {
        const user = document.getElementById('repo_user').value.trim();
        const pass = document.getElementById('repo_pass').value.trim();
        queryParams += `&username=${encodeURIComponent(user)}&password=${encodeURIComponent(pass)}`;
    }

    const resultDiv = document.getElementById('add-repo-result');
    resultDiv.innerHTML = _helmSpinner();

    try {
        // Usiamo l'endpoint con i query params aggiornati
        const result = await _helmPost(`/helm/repos${queryParams}`);
        resultDiv.innerHTML = _renderResultBox(result, `Repository "${name}" added successfully.`);
        if (result.success) {
            setTimeout(() => loadRepositories(), 1500);
        }
    } catch (err) {
        resultDiv.innerHTML = _renderResultBox({ success: false, stderr: err.message });
    }
}

async function updateRepos(repoName = null) {
    // Se repoName è null, aggiorna tutto, altrimenti solo quella specifica
    const btn = repoName ? null : document.getElementById('btnUpdateRepos');
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Updating...'; }
    
    const url = repoName ? `/helm/repos/update?name=${encodeURIComponent(repoName)}` : '/helm/repos/update';

    try {
        const result = await _helmPost(url);
        if (repoName) {
            showSuccess(`Repository "${repoName}" updated.`);
        } else {
            const resultDiv = document.getElementById('repo-action-result');
            if (resultDiv) resultDiv.innerHTML = _renderResultBox(result, "All repositories updated successfully.");
        }
    } catch (err) {
        showError(err.message);
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-sync"></i> Update All'; }
    }
}

function searchInRepo(repoName) {
    // Porta sulla sezione search con prefill del nome repo
    document.getElementById('menu-search')?.click();
    setTimeout(() => {
        const input = document.getElementById('chartSearchInput');
        if (input) { input.value = repoName + '/'; input.focus(); }
    }, 100);
}

// ---------------------------------------------------------------------------
// DEPLOY FROM ZIP — aligned with updated backend
// ---------------------------------------------------------------------------

// Accepted formats: all formats supported by the backend unpacker.
// Keep in sync with _ALLOWED in helm_routes.py.
const _ALLOWED_CHART_EXTENSIONS = [".zip", ".tgz", ".tar.gz", ".tar.bz2", ".tar.xz"];

function showZipUpload() {
    window.currentView = 'zip';
    const resArea = document.getElementById('resultArea');
    document.getElementById('controlsContainer').style.display = 'none';

    resArea.innerHTML = `
        <div class="deploy-container">
            <h2>Deploy from package</h2>
            <div class="info-note" style="background:rgba(var(--accent-rgb),0.08); border-left:4px solid var(--accent);
                 padding:12px 14px; border-radius:6px; margin-bottom:20px; font-size:0.85rem; line-height:1.5; color:var(--text-secondary);">
                <i class="fas fa-info-circle" style="color:var(--accent); margin-right:8px;"></i>
                Upload an archive containing a Helm chart directory (must include <code>Chart.yaml</code>).
                Supported formats: <code>.zip</code> &nbsp;<code>.tgz</code> &nbsp;<code>.tar.gz</code> &nbsp;<code>.tar.bz2</code> &nbsp;<code>.tar.xz</code>
            </div>

            <div style="display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-bottom:16px;">
                <div>
                    <label style="font-size:0.72rem; font-weight:600; color:var(--text-muted); text-transform:uppercase; display:block; margin-bottom:5px;">Release Name *</label>
                    <input type="text" id="zip_release_name" placeholder="my-release"
                        style="width:100%; padding:9px 12px; border-radius:8px; border:1px solid var(--border); font-size:0.85rem; box-sizing:border-box;">
                </div>
                <div>
                    <label style="font-size:0.72rem; font-weight:600; color:var(--text-muted); text-transform:uppercase; display:block; margin-bottom:5px;">Namespace</label>
                    <input type="text" id="zip_namespace" value="${window.currentNamespace}"
                        style="width:100%; padding:9px 12px; border-radius:8px; border:1px solid var(--border); font-size:0.85rem; box-sizing:border-box;">
                </div>
            </div>

            <div class="upload-zone" style="border:2px dashed var(--border); padding:28px; border-radius:12px; text-align:center; margin-bottom:16px; cursor:pointer;"
                 onclick="document.getElementById('zipFileInput').click()">
                <i class="fas fa-file-archive fa-2x" style="color:var(--accent); margin-bottom:10px;"></i><br>
                <span style="font-size:0.88rem; color:var(--text-secondary)">Click to select a package</span>
                <input type="file" id="zipFileInput"
                       accept=".zip,.tgz,.tar.gz,.tar.bz2,.tar.xz"
                       style="display:none"
                       onchange="handleZipSelection(event)">
                <div id="zipFileDisplay" style="margin-top:10px; font-size:0.75rem; color:var(--text-muted)">No file selected</div>
            </div>

            <label style="font-size:0.72rem; font-weight:600; color:var(--text-muted); text-transform:uppercase; display:block; margin-bottom:5px;">
                Values Override (JSON)
                <span style="font-weight:400; font-size:0.7rem; text-transform:none; margin-left:8px; color:#94a3b8">optional</span>
            </label>
            <textarea id="zip_values" rows="4" placeholder='{ "replicaCount": 1 }'
                style="width:100%; padding:10px; border-radius:8px; border:1px solid var(--border);
                       font-family:monospace; font-size:0.8rem; box-sizing:border-box; margin-bottom:14px;"></textarea>

            <div style="display:flex; align-items:center; gap:15px; margin-top:14px;">
                <button onclick="lintZipChart()" class="btn-action" id="btnLintZip"
                        style="background:#fff; color:var(--accent); border:1px solid var(--accent); padding:10px 20px;">
                    <i class="fas fa-stethoscope"></i> Lint
                </button>
                <button onclick="executeZipDeploy()" class="btn-action" style="flex:1; padding:10px 20px;" id="zipDeployBtn">
                    <i class="fas fa-upload"></i> Upload & Deploy
                </button>
                <label style="display:flex; align-items:center; gap:7px; font-size:0.85rem; cursor:pointer; color:var(--accent); font-weight:600; padding:10px 0;">
                    <input type="checkbox" id="zip_dry_run" style="width:16px; height:16px; accent-color:var(--accent);">
                    Simulate
                </label>
            </div>
            
            <div id="zip-result" style="margin-top:14px;"></div>
        </div>`;
}

function handleZipSelection(event) {
    const file = event.target.files[0];
    if (!file) return;

    // Client-side format check — mirrors backend _ALLOWED list
    const name = file.name.toLowerCase();
    const allowed = _ALLOWED_CHART_EXTENSIONS.some(ext => name.endsWith(ext));
    if (!allowed) {
        showError(`Unsupported format. Allowed: ${_ALLOWED_CHART_EXTENSIONS.join(', ')}`);
        event.target.value = '';
        document.getElementById('zipFileDisplay').textContent = 'No file selected';
        return;
    }

    document.getElementById('zipFileDisplay').textContent =
        `Selected: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
}

async function executeZipDeploy() {
    const releaseName = document.getElementById('zip_release_name')?.value?.trim();
    const namespace   = document.getElementById('zip_namespace')?.value?.trim() || window.currentNamespace;
    const fileInput   = document.getElementById('zipFileInput');
    const valuesRaw   = document.getElementById('zip_values')?.value?.trim();
    const dryRun      = document.getElementById('zip_dry_run')?.checked; // <--- LETTURA DRY RUN
    const resultDiv   = document.getElementById('zip-result');

    if (!releaseName) { showError("Release name is required."); return; }
    if (!fileInput.files[0]) { showError("Please select a package file."); return; }

    // Validate JSON values before sending
    let valuesJson = null;
    if (valuesRaw) {
        try {
            JSON.parse(valuesRaw);
            valuesJson = valuesRaw;
        } catch {
            showError("Invalid JSON in Values Override field.");
            return;
        }
    }

    const btn = document.getElementById('zipDeployBtn');
    btn.disabled = true;
    // Feedback visivo diverso per la simulazione
    btn.innerHTML = dryRun 
        ? '<i class="fas fa-spinner fa-spin"></i> Simulating...' 
        : '<i class="fas fa-spinner fa-spin"></i> Uploading & Deploying...';
    resultDiv.innerHTML = '';

    try {
        // FIX: values_json and other options are Query parameters on the backend,
        // NOT FormData fields. Only the file itself goes in FormData.
        const qs = new URLSearchParams({
            atomic:           'false',
            wait:             'false',
            create_namespace: 'true',
            dry_run:          dryRun.toString() // <--- PASSAGGIO DEL PARAMETRO
        });
        if (valuesJson) qs.set('values_json', valuesJson);

        const formData = new FormData();
        formData.append('file', fileInput.files[0]);

        const url = `/helm/namespaces/${namespace}/releases/${releaseName}/package?${qs}`;
        const result = await apiCall(url, 'POST', false, formData);

        if (dryRun && result.success) {
            // Se è un dry-run, mostriamo il manifest generato in un blocco di codice
            const manifestYaml = result.data?.manifest || "(No manifest generated)";
            resultDiv.innerHTML = `
                <div style="margin-top:16px; padding:16px; background:#f8fafc; border-radius:10px; border:1px solid var(--accent);">
                    <div style="display:flex; align-items:center; gap:8px; margin-bottom:10px;">
                        <i class="fas fa-flask" style="color:var(--accent);"></i>
                        <b style="font-size:0.9rem; color:var(--accent);">Simulation Success (Dry-Run)</b>
                    </div>
                    <pre style="font-size:0.75rem; background:#1e293b; color:#e2e8f0; border-radius:8px; padding:14px; overflow-x:auto; max-height:400px; white-space:pre-wrap; margin:0;">${manifestYaml}</pre>
                </div>
            `;
        } else {
            // Comportamento standard per il deploy reale
            resultDiv.innerHTML = _renderResultBox(result, `Chart deployed as "${releaseName}" in namespace "${namespace}".`);
            if (result.success) setTimeout(() => loadReleases(), 2000);
        }

    } catch (err) {
        resultDiv.innerHTML = _renderResultBox({ success: false, stderr: err.message });
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-upload"></i> Upload & Deploy';
    }
}

// ---------------------------------------------------------------------------
// LINT — remote chart reference
// ---------------------------------------------------------------------------

async function lintChart(chartRef, version) {
    const existing = document.getElementById('lint-result-panel');
    if (existing) existing.remove();

    const resultsDiv = document.getElementById('chartSearchResults');
    resultsDiv.insertAdjacentHTML('beforeend', `
        <div id="lint-result-panel" style="margin-top:16px; padding:16px; background:#f8fafc;
             border-radius:10px; border:1px solid var(--border);">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                <b style="font-size:0.9rem;">
                    <i class="fas fa-stethoscope" style="color:var(--accent); margin-right:8px;"></i>
                    Lint: ${chartRef}
                </b>
                <button onclick="document.getElementById('lint-result-panel').remove()"
                        style="background:none; border:none; color:var(--text-muted); cursor:pointer; font-size:1.1rem;">&times;</button>
            </div>
            <div id="lint-result-content">${_helmSpinner()}</div>
        </div>`);

    try {
        const fd = new FormData();
        fd.append('chart_ref', chartRef);
        if (version) fd.append('version', version);
        fd.append('strict', 'false');

        // FIX: backend returns HTTP 422 (not 200) when lint has errors.
        // _callLint handles both success (200) and lint-error (422) responses.
        const result = await _callLint(fd);
        document.getElementById('lint-result-content').innerHTML = _renderLintResult(result);

    } catch (err) {
        document.getElementById('lint-result-content').innerHTML =
            `<p style="color:#ef4444; font-size:0.85rem;">Error: ${err.message}</p>`;
    }
}

// ---------------------------------------------------------------------------
// LINT — local package upload
// ---------------------------------------------------------------------------

async function lintZipChart() {
    const fileInput = document.getElementById('zipFileInput');
    const resultDiv = document.getElementById('zip-result');

    if (!fileInput?.files[0]) { showError("Select a file first."); return; }

    const btn = document.getElementById('btnLintZip');
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Linting...'; }
    resultDiv.innerHTML = '';

    try {
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        formData.append('strict', 'false');

        // FIX: use _callLint to handle both 200 and 422 responses correctly
        const result = await _callLint(formData);
        resultDiv.innerHTML = _renderLintResult(result);

    } catch (err) {
        resultDiv.innerHTML = `<p style="color:#ef4444; font-size:0.85rem;">Error: ${err.message}</p>`;
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-stethoscope"></i> Lint'; }
    }
}

// ---------------------------------------------------------------------------
// _callLint — shared fetch wrapper for the lint endpoint
//
// The backend returns:
//   HTTP 200  → lint passed (no errors, possibly warnings)
//   HTTP 422  → lint ran but found errors — body is a structured JSON detail
//   HTTP 4xx/5xx → unexpected failure
//
// apiCall() throws on any non-2xx status, so we can't use it for 422
// (which carries useful structured data we want to render, not discard).
// This wrapper calls fetch directly and normalises both cases into the same
// result shape that _renderLintResult expects.
// ---------------------------------------------------------------------------

async function _callLint(formData) {
    const response = await fetch(`${API_BASE}/helm/charts/lint`, {
        method:      'POST',
        credentials: 'include',
        body:        formData,
        // Do NOT set Content-Type — browser sets it automatically with boundary
    });

    const data = await response.json().catch(() => ({}));

    if (response.status === 422) {
        // Backend sends: { detail: { message, stdout, stderr, has_errors, has_warnings } }
        const detail = data.detail || {};
        return {
            success:      false,
            stdout:       detail.stdout  || '',
            stderr:       detail.stderr  || '',
            has_errors:   detail.has_errors   ?? true,
            has_warnings: detail.has_warnings ?? false,
        };
    }

    if (!response.ok) {
        // Unexpected error — surface the detail message
        throw new Error(data.detail?.message || data.detail || `HTTP ${response.status}`);
    }

    // HTTP 200 — lint passed
    return {
        success:      true,
        stdout:       data.stdout  || '',
        stderr:       data.stderr  || '',
        has_errors:   false,
        has_warnings: data.has_warnings ?? false,
    };
}

// ---------------------------------------------------------------------------
// _renderLintResult — shared renderer (unchanged)
// ---------------------------------------------------------------------------

function _renderLintResult(result) {
    const hasErrors   = result.has_errors;
    const hasWarnings = result.has_warnings;
    const output      = result.stdout || result.stderr || "(no output)";

    const color = hasErrors ? "#ef4444" : hasWarnings ? "#f59e0b" : "#10b981";
    const icon  = hasErrors ? "fa-times-circle"
                : hasWarnings ? "fa-exclamation-triangle"
                : "fa-check-circle";
    const label = hasErrors   ? "Lint failed — errors found"
                : hasWarnings ? "Lint passed with warnings"
                : "Lint passed — no issues found";

    return `
        <div style="margin-bottom:10px; display:flex; align-items:center; gap:8px;">
            <i class="fas ${icon}" style="color:${color}; font-size:1.1rem;"></i>
            <span style="font-size:0.88rem; font-weight:600; color:${color};">${label}</span>
        </div>
        <pre style="margin:0; font-size:0.75rem; background:#1e293b; color:#e2e8f0;
                    border-radius:8px; padding:14px; overflow-x:auto;
                    max-height:260px; white-space:pre-wrap;">${output}</pre>`;
}


