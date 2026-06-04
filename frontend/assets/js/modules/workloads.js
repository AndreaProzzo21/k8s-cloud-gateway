async function loadPods() {
    currentView = 'pods';
    renderLabelFilter(true);
    
    const ns = window.currentNamespace;
    const resArea = document.getElementById('resultArea');
    
    const labelSelector = document.getElementById('labelFilter')?.value || '';
    let url = `/namespaces/${ns}/pods`;
    if (labelSelector) url += `?label_selector=${encodeURIComponent(labelSelector)}`;

    resArea.innerHTML = '<div style="text-align:center; padding:20px;"><i class="fas fa-spinner fa-spin fa-2x"></i></div>';

    try {
        const data = await apiCall(url);
        let html = `
            <h2>Pods [${ns}]</h2>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Node</th>
                        <th>Labels</th>
                        <th>Status</th>
                        <th>IP</th>
                        <th style="text-align:right">Actions</th>
                    </tr>
                </thead>
                <tbody>`;
        
        data.forEach(p => {
            const sClass = p.status.toLowerCase() === 'running' ? 'status-running' : 'status-pending';
            const nodeDisplay = p.node_name 
                ? `<span style="font-size:0.75rem; color:var(--accent); font-weight:600;">${p.node_name}</span>`
                : '<span style="color:var(--text-muted); font-size:0.75rem;">Unassigned</span>';

            // Aggiungiamo onclick sulla riga e la classe 'clickable-row'
            html += `
                <tr onclick="inspectResource('pods', '${p.name}')" class="clickable-row">
                    <td><b class="resource-name">${p.name}</b></td>
                    <td>${nodeDisplay}</td>
                    <td>${renderLabels(p.labels)}</td>
                    <td><span class="badge ${sClass}">${p.status}</span></td>
                    <td><code style="font-size:0.75rem">${p.pod_ip || 'N/A'}</code></td>
                    <td style="text-align:right; white-space: nowrap;" onclick="event.stopPropagation()">
                        <button onclick="viewLogs('${p.name}', this)" class="btn-small table-btn" title="View Logs">
                            <i class="fas fa-terminal"></i>
                        </button>
                        <button onclick="downloadLogs('${p.name}')" class="btn-small table-btn" title="Download Logs">
                            <i class="fas fa-file-download"></i>
                        </button>
                        <button onclick="deleteResource('pods', '${p.name}')" class="btn-small delete-btn" title="Delete Pod">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>`;
        });

        resArea.innerHTML = data.length > 0 
            ? html + '</tbody></table><div id="logConsoleArea"></div>' 
            : `<p style="text-align:center; margin-top:20px; color:var(--text-muted);">No Pod found in namespace ${ns}.</p>`;

    } catch (err) { 
        if (err.message === "RESTRICTED") {
            renderRestrictedAccess(); 
        } else {
            showError(err.message);
        }
    }
}


async function loadDeployments() {
    currentView = 'deployments';
    renderLabelFilter(true);
    
    const ns = window.currentNamespace;
    const resArea = document.getElementById('resultArea');
    
    const labelSelector = document.getElementById('labelFilter')?.value || '';
    let url = `/namespaces/${ns}/deployments`;
    if (labelSelector) url += `?label_selector=${encodeURIComponent(labelSelector)}`;

    resArea.innerHTML = '<div style="text-align:center; padding:20px;"><i class="fas fa-spinner fa-spin fa-2x"></i></div>';

    try {
        const data = await apiCall(url);
        let html = `
            <h2>Deployments [${ns}]</h2>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Labels</th>
                        <th>Replicas</th>
                        <th>Status</th>
                        <th style="text-align:right">Actions</th>
                    </tr>
                </thead>
                <tbody>`;

        data.forEach(d => {
            // Riferimento allo stato per il badge
            const isHealthy = d.replicas_ready === d.replicas_desired;
            const statusClass = isHealthy ? 'status-running' : 'status-pending';

            html += `
                <tr onclick="inspectResource('deployments', '${d.name}')" class="clickable-row">
                    <td><b class="resource-name">${d.name}</b></td>
                    <td>${renderLabels(d.labels)}</td>
                    <td><b>${d.replicas_ready}</b>/${d.replicas_desired}</td>
                    <td><span class="badge ${statusClass}">${d.status}</span></td>
                    <td style="text-align:right; white-space: nowrap;" onclick="event.stopPropagation()">
                        <button onclick="scaleDeploy('${d.name}', ${d.replicas_desired})" class="btn-small scale-btn" title="Scale"><i class="fas fa-layer-group"></i></button>
                        <button onclick="restartDeploy('${d.name}')" class="btn-small restart-btn" title="Restart Rollout"><i class="fas fa-sync"></i></button>
                        <button onclick="deleteResource('deployments', '${d.name}')" class="btn-small delete-btn" title="Delete Deployment"><i class="fas fa-trash"></i></button>
                    </td>
                </tr>`;
        });
        
        resArea.innerHTML = data.length > 0 
            ? html + '</tbody></table>' 
            : `<p style="text-align:center; margin-top:20px; color:var(--text-muted);">No Deployment found in namespace ${ns}.</p>`;
        
    } catch (err) { 
        if (err.message === "RESTRICTED") {
            renderRestrictedAccess(); 
        } else {
            showError(err.message);
        }
    }
}

async function restartDeploy(name) {
    const confirmed = await showConfirm(
        "Confirm Restart", 
        `Are you sure you want to restart <strong>${name}</strong>?`,
        true // Imposta il tasto rosso per azioni pericolose
    );
    if (!confirmed) return;
    try {
        await apiCall(`/namespaces/${window.currentNamespace}/deployments/${name}/restart`, 'POST');
        showSuccess("Deployment successfully restarted")
        loadDeployments();
    } catch (err) { showError(err.message); }
}

async function scaleDeploy(name, current) {
    const n = await showPrompt("Current Replicas:", current);
    if (n === null) return;
    try {
        await apiCall(`/namespaces/${window.currentNamespace}/deployments/${name}/scale?replicas=${n}`, 'PATCH');
        loadDeployments();
    } catch (err) { showError(err.message); }
}

async function viewLogs(name, btn) {
    const row = btn.closest('tr');
    const existingLog = document.getElementById(`logs-${name}`);

    // Toggle: Se i log sono già aperti, li rimuoviamo
    if (existingLog) {
        existingLog.remove();
        return;
    }

    try {
        // Inseriamo una riga di caricamento immediata
        row.insertAdjacentHTML('afterend', `
            <tr id="logs-${name}" class="log-row">
                <td colspan="6">
                    <div class="log-container">
                        <div style="display:flex; justify-content:space-between; color:#94a3b8; margin-bottom:5px;">
                            <small>Streaming logs for <b>${name}</b> (newest first)...</small>
                            <button onclick="this.closest('tr').remove()" style="background:none; border:none; color:#94a3b8; cursor:pointer;">&times;</button>
                        </div>
                        <pre id="pre-${name}">Loading...</pre>
                    </div>
                </td>
            </tr>`);

        const logs = await apiCall(`/namespaces/${window.currentNamespace}/pods/${name}/logs?tail=50`, 'GET', true);
        
        if (logs) {
            // Logica di inversione:
            // 1. .trim() rimuove spazi vuoti inutili all'inizio/fine
            // 2. .split('\n') crea un array di righe
            // 3. .reverse() inverte l'ordine dell'array
            // 4. .join('\n') ricompone la stringa
            const reversedLogs = logs.trim().split('\n').reverse().join('\n');
            document.getElementById(`pre-${name}`).textContent = reversedLogs;
        } else {
            document.getElementById(`pre-${name}`).textContent = "No logs available.";
        }
        
    } catch (err) {
        showError(err.message);
        document.getElementById(`logs-${name}`)?.remove();
    }
}

async function downloadLogs(name) {
    const logs = await apiCall(`/namespaces/${window.currentNamespace}/pods/${name}/logs`, 'GET', true);
    const blob = new Blob([logs], { type: 'text/plain' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `${name}_logs.txt`;
    document.body.appendChild(a); a.click(); a.remove();
}

function _renderApplyReport(res) {
    const details = res.details || [];
    // Dividiamo i messaggi in base al contenuto (semplice euristica)
    const errors = details.filter(d => d.toLowerCase().includes('error') || d.toLowerCase().includes('failed'));
    const success = details.filter(d => !errors.includes(d));

    let html = `<div class="apply-result-container">`;

    // Sezione Successi
    if (success.length > 0) {
        html += `
            <div class="apply-box success">
                <div class="apply-box-header"><i class="fas fa-check-circle"></i> Resources Applied</div>
                <ul>${success.map(s => `<li>${s}</li>`).join('')}</ul>
            </div>`;
    }

    // Sezione Errori
    if (errors.length > 0) {
        html += `
            <div class="apply-box danger">
                <div class="apply-box-header"><i class="fas fa-exclamation-triangle"></i> Deployment Errors</div>
                <div class="apply-error-scroll">
                    <ul>${errors.map(e => `<li><code>${e}</code></li>`).join('')}</ul>
                </div>
            </div>`;
    }

    html += `</div>`;
    return html;
}

async function executeApply() {
    const yamlContent = document.getElementById('yamlEditor').value;
    if (!yamlContent.trim()) return;

    const reportDiv = document.getElementById('applyReport');
    const btn = document.querySelector('.btn-apply-main'); // Assicurati di avere una classe sul tasto
    
    // UI Feedback iniziale
    reportDiv.innerHTML = `
        <div style="text-align:center; padding:20px;">
            <i class="fas fa-spinner fa-spin"></i> Communicating with Kubernetes API...
        </div>`;
    if(btn) btn.disabled = true;

    try {
        const formData = new FormData();
        formData.append('file', new Blob([yamlContent], { type: 'text/yaml' }), 'resource.yaml');
        
        const res = await apiCall(`/apply`, 'POST', false, formData);

        // Usiamo l'helper per renderizzare il risultato
        reportDiv.innerHTML = _renderApplyReport(res);

    } catch (err) {
        // Gestione errore catastrofico (es. rete o 500)
        reportDiv.innerHTML = `
            <div class="apply-box danger">
                <div class="apply-box-header">Critical System Error</div>
                <p>${err.message}</p>
            </div>`;
    } finally {
        if(btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-magic"></i> Apply Manifest';
        }
    }
}

async function loadEvents() {
    currentView = 'events';
    const ns = window.currentNamespace;
    const resArea = document.getElementById('resultArea');
    resArea.innerHTML = '<div style="text-align:center; padding:40px;"><i class="fas fa-spinner fa-spin fa-2x"></i></div>';

    try {
        const data = await apiCall(`/namespaces/${ns}/events`);
        
        let html = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                <h2 style="margin:0;">Events Log [${ns}]</h2>
                <small style="color:var(--text-muted)">Last ${data.length} events</small>
            </div>
            
            <div style="max-height: 500px; overflow-y: auto; border: 1px solid var(--border); border-radius: 12px; background: #fff;">
                <table class="data-table" style="margin:0; border:none;">
                    <thead style="position: sticky; top: 0; background: #f8fafc; z-index: 1;">
                        <tr>
                            <th style="width: 180px;">Time</th>
                            <th style="width: 130px;">Reason</th>
                            <th>Object & Message</th>
                        </tr>
                    </thead>
                    <tbody>`;

        if (!data || data.length === 0) {
            html += `<tr><td colspan="3" style="text-align:center; padding:30px; color:var(--text-muted);">No recent events.</td></tr>`;
        } else {
            data.forEach(e => {
                // Utilizziamo l'orario diretto senza trasformazioni pericolose
                const displayTime = e.time || "N/A";

                const isWarning = e.reason.toLowerCase().includes('fail') || 
                                e.reason.toLowerCase().includes('kill') || 
                                e.reason.toLowerCase().includes('backoff') ||
                                e.reason.toLowerCase().includes('unhealthy');
                
                const rowStyle = isWarning ? 'background-color: #fff1f2;' : '';
                const reasonColor = isWarning ? '#e11d48' : '#475569';

                html += `
                    <tr style="${rowStyle}">
                        <td>
                            <small style="font-family:monospace; color:#64748b; font-size:0.7rem;">${displayTime}</small>
                        </td>
                        <td>
                            <b style="color:${reasonColor}; font-size:0.8rem;">${e.reason}</b>
                        </td>
                        <td>
                            <div style="font-size:0.85rem; line-height:1.4;">
                                <span style="color:var(--accent); font-weight:600;">${e.object || 'Unknown'}</span><br>
                                <span style="color:#334155;">${e.message}</span>
                            </div>
                        </td>
                    </tr>`;
            });
        }

        resArea.innerHTML = html + '</tbody></table></div>';
    } catch (err) { 
        if (err.message === "RESTRICTED") {
            renderRestrictedAccess(); 
        } else {
            showError(err.message);
        } 
    }
}



async function deleteResource(type, name) {
    const confirmed = await showConfirm(
        "Confirm Deletion", 
        `Are you sure you want to delete ${type} <strong>${name}</strong>? This action cannot be undone.`,
        true // Imposta il tasto rosso per azioni pericolose
    );

    if (!confirmed) return;

    const ns = window.currentNamespace;
    const url = `/namespaces/${ns}/${type}/${name}`;

    try {
        await apiCall(url, 'DELETE'); 
        showSuccess(`${type} '${name}' successfully deleted.`);

        refreshCurrentView(); 
        
    } catch (err) {
            showError(err.message);
        }
    
}

async function deleteNamespace(name) {
    // 1. Protezione per i namespace di sistema
    const protectedNamespaces = ['default', 'kube-system', 'kube-public', 'kube-node-lease', 'kube-flannel'];
    if (protectedNamespaces.includes(name)) {
        showError(`Error: Namespace '${name}' is a system resource. Cannot be deleted by the Gateway.`);
        return;
    }

    // 2. Doppia conferma (l'eliminazione di un NS cancella TUTTO ciò che contiene)
    const confirmed = await showConfirm(
        "Confirm Deletion", 
        `Are you sure you want to delete <strong>${name}</strong>? This action cannot be undone.`,
        true // Imposta il tasto rosso per azioni pericolose
    );
    if (!confirmed) return;

    const confirmSecond = await showPrompt('Confirm',`To definitely delete the namespace type the name: (${name}):`);
    if (confirmSecond !== name) {
        showError("Names do not correspond. Namespace not deleted");
        return;
    }

    try {
        // L'URL corretto per un namespace è globale: /namespaces/{name}
        await apiCall(`/namespaces/${name}`, 'DELETE');
        
        showSuccess("Deletion Started", `The deletion process for '${name}' has started. It may appear as 'Terminating' for a few moments.`);
        // Ricarichiamo la lista dei namespace
        await loadNamespace();
        
    } catch (err) {
        showError(err.message);
      
    }
}

async function loadStatefulSets() {
    currentView = 'statefulsets';
    renderLabelFilter(true);
    
    const ns = window.currentNamespace;
    const resArea = document.getElementById('resultArea');
    
    // Recupero filtro (ora l'elemento esiste sicuramente perché chiamato sopra)
    const labelSelector = document.getElementById('labelFilter')?.value || '';
    let url = `/namespaces/${ns}/statefulsets`;
    if (labelSelector) url += `?label_selector=${encodeURIComponent(labelSelector)}`;

    resArea.innerHTML = '<div style="text-align:center; padding:20px;"><i class="fas fa-spinner fa-spin fa-2x"></i></div>';

    try {
        const data = await apiCall(url);
        let html = `
            <h2>StatefulSets [${ns}]</h2>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Service</th>
                        <th>Replicas</th>
                        <th>Age</th>
                        <th style="text-align:right">Actions</th>
                    </tr>
                </thead>
                <tbody>`;

        if (!data || data.length === 0) {
            html += `<tr><td colspan="5" style="text-align:center; padding:30px; color:var(--text-muted);">No StatefulSet found in namespace ${ns}.</td></tr>`;
        } else {
            data.forEach(s => {
                const isReady = s.replicas_ready === s.replicas_desired;
                const badgeClass = isReady ? 'status-running' : 'status-pending';
                
                html += `
                    <tr>
                        <td><b>${s.name}</b></td>
                        <td><code style="font-size:0.8rem">${s.service_name || '-'}</code></td>
                        <td><b>${s.replicas_ready}</b>/${s.replicas_desired}</td>
                        <td><small>${new Date(s.creation_timestamp).toLocaleDateString()}</small></td>
                        <td style="text-align:right">
                            <button onclick="if(confirm('Eliminare lo StatefulSet ${s.name}?')) deleteResource('statefulsets', '${s.name}')" 
                                    class="btn-small delete-btn" title="Delete StatefulSet">
                                <i class="fas fa-trash"></i>
                            </button>
                        </td>
                    </tr>`;
            });
        }
        
        resArea.innerHTML = html + '</tbody></table>';
        
    } catch (err) { 
        if (err.message === "RESTRICTED") {
            renderRestrictedAccess(); 
        } else {
            showError(err.message);
        }
    }
}

// =============================================================================
// DAEMONSETS
// =============================================================================

async function loadDaemonSets() {
    currentView = 'daemonsets';
    renderLabelFilter(true);

    const ns = window.currentNamespace;
    const resArea = document.getElementById('resultArea');

    const labelSelector = document.getElementById('labelFilter')?.value || '';
    let url = `/namespaces/${ns}/daemonsets`;
    if (labelSelector) url += `?label_selector=${encodeURIComponent(labelSelector)}`;

    resArea.innerHTML = '<div style="text-align:center; padding:20px;"><i class="fas fa-spinner fa-spin fa-2x"></i></div>';

    try {
        const data = await apiCall(url);

        let html = `
            <h2>DaemonSets [${ns}]</h2>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Labels</th>
                        <th>Desired</th>
                        <th>Ready</th>
                        <th>Available</th>
                        <th>Node Selector</th>
                        <th style="text-align:right">Actions</th>
                    </tr>
                </thead>
                <tbody>`;

        if (!data || data.length === 0) {
            html += `<tr><td colspan="7" style="text-align:center; padding:30px; color:var(--text-muted);">No DaemonSet found in namespace ${ns}.</td></tr>`;
        } else {
            data.forEach(ds => {
                const isReady = ds.ready === ds.desired;
                const badgeClass = isReady ? 'status-running' : 'status-pending';
                const badgeLabel = isReady ? 'Ready' : 'Degraded';

                const nodeSelectorHtml = ds.node_selector && Object.keys(ds.node_selector).length > 0
                    ? Object.entries(ds.node_selector).map(([k, v]) => `<code style="font-size:0.7rem">${k}=${v}</code>`).join(' ')
                    : '<span style="color:var(--text-muted); font-size:0.75rem;">All nodes</span>';

                html += `
                    <tr onclick="inspectResource('daemonsets', '${ds.name}')" class="clickable-row">
                        <td><b class="resource-name">${ds.name}</b></td>
                        <td>${renderLabels(ds.labels)}</td>
                        <td>${ds.desired}</td>
                        <td><b>${ds.ready}</b></td>
                        <td><span class="badge ${badgeClass}">${ds.available} ${badgeLabel}</span></td>
                        <td>${nodeSelectorHtml}</td>
                        <td style="text-align:right; white-space:nowrap;" onclick="event.stopPropagation()">
                            <button onclick="deleteResource('daemonsets', '${ds.name}')" class="btn-small delete-btn" title="Delete DaemonSet">
                                <i class="fas fa-trash"></i>
                            </button>
                        </td>
                    </tr>`;
            });
        }

        resArea.innerHTML = html + '</tbody></table>';

    } catch (err) {
        if (err.message === 'RESTRICTED') renderRestrictedAccess();
        else showError(err.message);
    }
}


// =============================================================================
// JOBS
// =============================================================================

async function loadJobs() {
    currentView = 'jobs';
    renderLabelFilter(true);

    const ns = window.currentNamespace;
    const resArea = document.getElementById('resultArea');

    const labelSelector = document.getElementById('labelFilter')?.value || '';
    let url = `/namespaces/${ns}/jobs`;
    if (labelSelector) url += `?label_selector=${encodeURIComponent(labelSelector)}`;

    resArea.innerHTML = '<div style="text-align:center; padding:20px;"><i class="fas fa-spinner fa-spin fa-2x"></i></div>';

    try {
        const data = await apiCall(url);

        let html = `
            <h2>Jobs [${ns}]</h2>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Labels</th>
                        <th>State</th>
                        <th style="text-align:center">✓</th>
                        <th style="text-align:center">✗</th>
                        <th style="text-align:center">~</th>
                        <th>Started</th>
                        <th style="text-align:right">Actions</th>
                    </tr>
                </thead>
                <tbody>`;

        if (!data || data.length === 0) {
            html += `<tr><td colspan="8" style="text-align:center; padding:30px; color:var(--text-muted);">No Job found in namespace ${ns}.</td></tr>`;
        } else {
            data.forEach(j => {
                const isComplete = j.succeeded > 0 && j.active === 0 && j.failed === 0;
                const hasFailed  = j.failed > 0;
                const badgeClass = isComplete ? 'status-running' : hasFailed ? 'status-error' : 'status-pending';
                const badgeLabel = isComplete ? 'Complete' : hasFailed ? 'Failed' : 'Running';

                const startDisplay = j.start_time
                    ? new Date(j.start_time).toLocaleString('it-IT', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' })
                    : '<span style="color:var(--text-muted)">—</span>';

                html += `
                    <tr onclick="inspectResource('jobs', '${j.name}')" class="clickable-row">
                        <td><b class="resource-name">${j.name}</b></td>
                        <td>${renderLabels(j.labels)}</td>
                        <td><span class="badge ${badgeClass}">${badgeLabel}</span></td>
                        <td style="text-align:center"><b style="color:#16a34a">${j.succeeded}</b></td>
                        <td style="text-align:center"><b style="color:${j.failed > 0 ? '#dc2626' : 'inherit'}">${j.failed}</b></td>
                        <td style="text-align:center">${j.active}</td>
                        <td><small style="color:var(--text-muted)">${startDisplay}</small></td>
                        <td style="text-align:right; white-space:nowrap;" onclick="event.stopPropagation()">
                            <button onclick="deleteResource('jobs', '${j.name}')" class="btn-small delete-btn" title="Delete Job">
                                <i class="fas fa-trash"></i>
                            </button>
                        </td>
                    </tr>`;
            });
        }

        resArea.innerHTML = html + '</tbody></table>';

    } catch (err) {
        if (err.message === 'RESTRICTED') renderRestrictedAccess();
        else showError(err.message);
    }
}


// =============================================================================
// CRONJOBS
// =============================================================================

async function loadCronJobs() {
    currentView = 'cronjobs';
    renderLabelFilter(true);

    const ns = window.currentNamespace;
    const resArea = document.getElementById('resultArea');

    const labelSelector = document.getElementById('labelFilter')?.value || '';
    let url = `/namespaces/${ns}/cronjobs`;
    if (labelSelector) url += `?label_selector=${encodeURIComponent(labelSelector)}`;

    resArea.innerHTML = '<div style="text-align:center; padding:20px;"><i class="fas fa-spinner fa-spin fa-2x"></i></div>';

    try {
        const data = await apiCall(url);

        let html = `
            <h2>CronJobs [${ns}]</h2>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Labels</th>
                        <th>Schedule</th>
                        <th>Status</th>
                        <th>Active</th>
                        <th>Last Schedule</th>
                        <th style="text-align:right">Actions</th>
                    </tr>
                </thead>
                <tbody>`;

        if (!data || data.length === 0) {
            html += `<tr><td colspan="7" style="text-align:center; padding:30px; color:var(--text-muted);">No CronJob found in namespace ${ns}.</td></tr>`;
        } else {
            data.forEach(cj => {
                const badgeClass = cj.suspend ? 'status-pending' : 'status-running';
                const badgeLabel = cj.suspend ? 'Suspended' : 'Active';

                const lastSched = cj.last_schedule
                    ? new Date(cj.last_schedule).toLocaleString()
                    : '<span style="color:var(--text-muted)">Never</span>';

                html += `
                    <tr onclick="inspectResource('cronjobs', '${cj.name}')" class="clickable-row">
                        <td><b class="resource-name">${cj.name}</b></td>
                        <td>${renderLabels(cj.labels)}</td>
                        <td><code style="font-size:0.8rem; background:#f1f5f9; padding:2px 6px; border-radius:4px;">${cj.schedule}</code></td>
                        <td><span class="badge ${badgeClass}">${badgeLabel}</span></td>
                        <td>${cj.active}</td>
                        <td><small>${lastSched}</small></td>
                        <td style="text-align:right; white-space:nowrap;" onclick="event.stopPropagation()">
                            <button onclick="deleteResource('cronjobs', '${cj.name}')" class="btn-small delete-btn" title="Delete CronJob">
                                <i class="fas fa-trash"></i>
                            </button>
                        </td>
                    </tr>`;
            });
        }

        resArea.innerHTML = html + '</tbody></table>';

    } catch (err) {
        if (err.message === 'RESTRICTED') renderRestrictedAccess();
        else showError(err.message);
    }
}


// =============================================================================
// HPA — invariato, nessuna inspect per ora
// =============================================================================

async function loadHPAs() {
    currentView = 'hpa';
    renderLabelFilter(true);

    const ns = window.currentNamespace;
    const resArea = document.getElementById('resultArea');

    const labelSelector = document.getElementById('labelFilter')?.value || '';
    let url = `/namespaces/${ns}/hpa`;
    if (labelSelector) url += `?label_selector=${encodeURIComponent(labelSelector)}`;

    resArea.innerHTML = '<div style="text-align:center; padding:20px;"><i class="fas fa-spinner fa-spin fa-2x"></i></div>';

    try {
        const data = await apiCall(url);

        let html = `
            <h2>Horizontal Pod Autoscalers [${ns}]</h2>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Labels</th>
                        <th>Target</th>
                        <th>Min</th>
                        <th>Max</th>
                        <th>Current</th>
                        <th>Desired</th>
                        <th style="text-align:right">Actions</th>
                    </tr>
                </thead>
                <tbody>`;

        if (!data || data.length === 0) {
            html += `<tr><td colspan="8" style="text-align:center; padding:30px; color:var(--text-muted);">No HPA found in namespace ${ns}.</td></tr>`;
        } else {
            data.forEach(hpa => {
                const atMax = hpa.current_replicas >= hpa.max_replicas;
                const replicaColor = atMax ? '#dc2626' : '#16a34a';

                html += `
                    <tr>
                        <td><b class="resource-name">${hpa.name}</b></td>
                        <td>${renderLabels(hpa.labels)}</td>
                        <td>
                            <span style="font-size:0.7rem; background:#f1f5f9; padding:2px 5px; border-radius:4px; color:#475569; font-weight:600;">${hpa.target_kind}</span>
                            <code style="font-size:0.8rem; margin-left:4px;">${hpa.target}</code>
                        </td>
                        <td>${hpa.min_replicas}</td>
                        <td>${hpa.max_replicas}</td>
                        <td><b style="color:${replicaColor}">${hpa.current_replicas}</b></td>
                        <td>${hpa.desired_replicas}</td>
                        <td style="text-align:right; white-space:nowrap;">
                            <button onclick="deleteResource('hpa', '${hpa.name}')" class="btn-small delete-btn" title="Delete HPA">
                                <i class="fas fa-trash"></i>
                            </button>
                        </td>
                    </tr>`;
            });
        }

        resArea.innerHTML = html + '</tbody></table>';

    } catch (err) {
        if (err.message === 'RESTRICTED') renderRestrictedAccess();
        else showError(err.message);
    }
}


// =============================================================================
// HELPER — DELETE CLUSTER-WIDE
// =============================================================================

async function deleteClusterResource(type, name) {
    const confirmed = await showConfirm(
        "Confirm Deletion",
        `Are you sure you want to delete ${type} <strong>${name}</strong>? This action cannot be undone.`,
        true
    );
    if (!confirmed) return;

    try {
        await apiCall(`/cluster/${type}/${name}`, 'DELETE');
        showSuccess(`${type} '${name}' successfully deleted.`);
        refreshCurrentView();
    } catch (err) {
        showError(err.message);
    }
}


// =============================================================================
// INSPECT + MODAL — completo
// =============================================================================

async function inspectResource(type, name) {
    const ns = window.currentNamespace;
    try {
        const data = await apiCall(`/namespaces/${ns}/${type}/${name}`);
        console.log("Dati ricevuti dal backend:", data);
        showInspectorModal(data);
    } catch (err) {
        showError("Incapable of retrieving details: " + err.message);
    }
}

function showInspectorModal(info) {
    let overlay = document.getElementById('inspector-overlay');

    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'inspector-overlay';
        overlay.style.cssText = `
            position: fixed;
            top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(15, 23, 42, 0.6);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 10000;
            backdrop-filter: blur(6px);
        `;
        document.body.appendChild(overlay);
        overlay.onclick = (e) => {
            if (e.target === overlay) overlay.style.display = 'none';
        };
    }

    overlay.style.display = 'flex';

    // --- RILEVAMENTO TIPO ---
    let type = 'Unknown';
    let icon = 'fa-info-circle';
    let accentColor = '#b59a00';

    if (info.pod_ip || info.host_ip) {
        type = 'Pod';
        icon = 'fa-cube';
        accentColor = '#b59a00';
    } else if (info.strategy || info.replicas_spec !== undefined) {
        type = 'Deployment';
        icon = 'fa-layer-group';
        accentColor = '#b59a00';
    } else if (info.cluster_ip || info.type) {
        type = 'Service';
        icon = 'fa-project-diagram';
        accentColor = '#b59a00';
    } else if (info.desired !== undefined && info.node_selector !== undefined) {
        type = 'DaemonSet';
        icon = 'fa-broadcast-tower';
        accentColor = '#7c3aed';
    } else if (info.schedule !== undefined) {
        type = 'CronJob';
        icon = 'fa-clock';
        accentColor = '#0369a1';
    } else if (info.succeeded !== undefined || info.completions !== undefined) {
        type = 'Job';
        icon = 'fa-play-circle';
        accentColor = '#16a34a';
    }

    const creationDate = info.creation_timestamp || info.start_time;
    const formattedDate = creationDate ? new Date(creationDate).toLocaleString() : 'N/A';

    // --- GRID DINAMICA ---
    let gridHtml = '';
    if (type === 'Pod') {
        gridHtml = `
            <div class="grid-item"><strong>Status</strong> <span class="badge ${info.status?.toLowerCase() === 'running' ? 'status-running' : 'status-pending'}">${info.status}</span></div>
            <div class="grid-item"><strong>Node</strong> <span>${info.node_name || 'Unassigned'}</span></div>
            <div class="grid-item"><strong>Pod IP</strong> <code>${info.pod_ip || 'N/A'}</code></div>
            <div class="grid-item"><strong>Host IP</strong> <code>${info.host_ip || 'N/A'}</code></div>
        `;
    } else if (type === 'Deployment') {
        gridHtml = `
            <div class="grid-item"><strong>Strategy</strong> <span>${info.strategy || 'N/A'}</span></div>
            <div class="grid-item"><strong>Desired</strong> <span>${info.replicas_spec}</span></div>
            <div class="grid-item"><strong>Updated</strong> <span>${info.replicas_status?.updated || 0}</span></div>
            <div class="grid-item"><strong>Available</strong> <span class="badge status-running">${info.replicas_status?.available || 0}</span></div>
        `;
    } else if (type === 'Service') {
        gridHtml = `
            <div class="grid-item"><strong>Type</strong> <span>${info.type || 'N/A'}</span></div>
            <div class="grid-item"><strong>Cluster IP</strong> <code>${info.cluster_ip || 'N/A'}</code></div>
            <div class="grid-item"><strong>Session Affinity</strong> <span>${info.session_affinity || 'None'}</span></div>
            <div class="grid-item"><strong>Selector</strong> <span style="font-size:0.7rem; color:#718096;">${info.selector ? Object.entries(info.selector).map(([k,v]) => `${k}=${v}`).join(', ') : 'None'}</span></div>
        `;
    } else if (type === 'DaemonSet') {
        gridHtml = `
            <div class="grid-item"><strong>Desired</strong> <span>${info.desired}</span></div>
            <div class="grid-item"><strong>Ready</strong> <span class="badge ${info.ready === info.desired ? 'status-running' : 'status-pending'}">${info.ready} / ${info.desired}</span></div>
            <div class="grid-item"><strong>Available</strong> <span>${info.available}</span></div>
            <div class="grid-item"><strong>Node Selector</strong> <span style="font-size:0.7rem; color:#718096;">${info.node_selector && Object.keys(info.node_selector).length > 0 ? Object.entries(info.node_selector).map(([k,v]) => `${k}=${v}`).join(', ') : 'All nodes'}</span></div>
        `;
    } else if (type === 'CronJob') {
        gridHtml = `
            <div class="grid-item"><strong>Schedule</strong> <code style="font-size:0.8rem">${info.schedule}</code></div>
            <div class="grid-item"><strong>Status</strong> <span class="badge ${info.suspend ? 'status-pending' : 'status-running'}">${info.suspend ? 'Suspended' : 'Active'}</span></div>
            <div class="grid-item"><strong>Active Jobs</strong> <span>${info.active}</span></div>
            <div class="grid-item"><strong>Last Schedule</strong> <span>${info.last_schedule ? new Date(info.last_schedule).toLocaleString() : 'Never'}</span></div>
        `;
    } else if (type === 'Job') {
        const jobState = info.succeeded > 0 && info.active === 0 ? 'status-running'
                       : info.failed > 0 ? 'status-error'
                       : 'status-pending';
        const jobLabel = info.succeeded > 0 && info.active === 0 ? 'Complete'
                       : info.failed > 0 ? 'Failed'
                       : 'Running';
        gridHtml = `
            <div class="grid-item"><strong>State</strong> <span class="badge ${jobState}">${jobLabel}</span></div>
            <div class="grid-item"><strong>Completions</strong> <span>${info.completions ?? '∞'}</span></div>
            <div class="grid-item"><strong>Succeeded</strong> <span style="color:#16a34a; font-weight:600;">${info.succeeded}</span></div>
            <div class="grid-item"><strong>Failed</strong> <span style="color:${info.failed > 0 ? '#dc2626' : 'inherit'}; font-weight:600;">${info.failed}</span></div>
        `;
    }

    // --- PORTE (solo Service) ---
    let portsSection = '';
    if (type === 'Service' && info.ports && info.ports.length > 0) {
        portsSection = `
            <div class="ins-section">
                <h4><i class="fas fa-plug"></i> Service Ports</h4>
                <div class="containers-list">
                    ${info.ports.map(p => `
                        <div class="container-subcard" style="border-left: 3px solid #b59a00;">
                            <div style="display:flex; justify-content:space-between; align-items:center;">
                                <span style="font-weight:600; font-size:0.85rem;">${p.name || 'unnamed'}</span>
                                <span class="badge" style="background:#f1f5f9; color:#475569;">${p.protocol}</span>
                            </div>
                            <div style="margin-top:5px; font-size:0.8rem;">
                                <span>Port: <strong>${p.port}</strong></span>
                                <i class="fas fa-long-arrow-alt-right" style="margin:0 8px; color:#cbd5e0;"></i>
                                <span>Target: <strong>${p.target_port}</strong></span>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    // --- ANNOTATIONS ---
    const annotationsHtml = info.annotations && Object.keys(info.annotations).length > 0
        ? Object.entries(info.annotations)
            .filter(([k]) => !k.includes('kubectl.kubernetes.io/last-applied-configuration'))
            .map(([k, v]) => `
                <div class="annotation-item">
                    <span class="ann-key">${k}:</span> <span class="ann-val">${v}</span>
                </div>
            `).join('')
        : '<span class="none-text">No annotations found</span>';

    // --- COSTRUZIONE FINALE ---
    overlay.innerHTML = `
        <div class="inspector-card animate-slide-up">
            <div class="inspector-header">
                <div class="header-title-group">
                    <i class="fas ${icon} icon-main" style="color: ${accentColor}"></i>
                    <div>
                        <div style="display:flex; align-items:center; gap:8px;">
                            <h3 style="margin:0;">${info.name}</h3>
                            <span style="font-size:0.65rem; background:rgba(0,0,0,0.05); padding:2px 6px; border-radius:4px; text-transform:uppercase; letter-spacing:0.5px; font-weight:700; color:#666;">${type}</span>
                        </div>
                        <small>${info.namespace} • Resource v.${info.resource_version || '1'}</small>
                    </div>
                </div>
                <button class="close-ins-btn" onclick="document.getElementById('inspector-overlay').style.display='none'">
                    <i class="fas fa-times"></i>
                </button>
            </div>

            <div class="inspector-body">
                <div class="ins-section">
                    <h4><i class="fas fa-list-ul"></i> Configuration & Status</h4>
                    <div class="ins-grid">
                        ${gridHtml}
                        <div class="grid-item" style="grid-column: span 2;"><strong>Created at</strong> <span>${formattedDate}</span></div>
                    </div>
                </div>

                ${portsSection}

                ${info.containers ? `
                <div class="ins-section">
                    <h4><i class="fas fa-box-open"></i> Containers (${info.containers.length})</h4>
                    <div class="containers-list">
                        ${info.containers.map(c => `
                            <div class="container-subcard">
                                <div class="subcard-header">
                                    <span class="cont-name"><i class="fas fa-microchip"></i> ${c.name}</span>
                                    ${c.ready !== undefined ?
                                        `<span class="badge ${c.ready ? 'status-running' : 'status-pending'}">${c.ready ? 'Ready' : 'Not Ready'}</span>`
                                        : ''}
                                </div>
                                <div class="subcard-body">
                                    <p class="img-line"><strong>Image:</strong> <code>${c.image}</code></p>
                                    <div style="display:flex; justify-content:space-between; align-items:center;">
                                        ${c.restart_count !== undefined ? `<span class="restart-line"><strong>Restarts:</strong> ${c.restart_count}</span>` : '<span></span>'}
                                        ${c.ports && c.ports.length > 0 ? `<span style="font-size:0.7rem; color:#718096;"><i class="fas fa-door-open"></i> Ports: ${c.ports.join(', ')}</span>` : ''}
                                    </div>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>` : ''}

                <div class="ins-section">
                    <h4><i class="fas fa-tags"></i> Labels</h4>
                    <div class="labels-container" style="display: flex; flex-wrap: wrap; gap: 6px; max-height: 180px; overflow-y: auto; padding: 4px;">
                        ${info.labels && Object.keys(info.labels).length > 0
                            ? Object.entries(info.labels).map(([k, v]) => `
                                <div class="label-pill" style="display: flex; align-items: center; background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 4px; font-size: 0.72rem; overflow: hidden; white-space: nowrap;">
                                    <span style="background: #e2e8f0; padding: 2px 6px; color: #475569; font-weight: 600; border-right: 1px solid #cbd5e0;">${k}</span>
                                    <span style="padding: 2px 6px; color: #1e293b;">${v}</span>
                                </div>
                            `).join('')
                            : '<span class="none-text">No labels assigned</span>'
                        }
                    </div>
                </div>

                <div class="ins-section">
                    <h4><i class="fas fa-sticky-note"></i> Annotations</h4>
                    <div class="annotations-wrapper" style="max-height: 150px; overflow-y: auto;">
                        ${annotationsHtml}
                    </div>
                </div>
            </div>
        </div>
    `;
}