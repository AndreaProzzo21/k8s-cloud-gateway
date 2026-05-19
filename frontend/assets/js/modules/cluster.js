async function addNewNamespace() {
    // Custom prompt for a consistent "Cyber Dark" UI
    const name = await showPrompt("New Namespace", "Enter the name for the new Namespace:");

    // Exit if the user cancels or provides an empty input
    if (!name || name.trim() === "") return;

    // K8s best practice: trim and lowercase the input
    const cleanName = name.trim().toLowerCase();

    // Basic K8s name validation (lowercase, numbers, dashes)
    const dnsRegex = /^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/;
    if (!dnsRegex.test(cleanName)) {
        showError("Invalid name. Use only lowercase letters, numbers, and dashes.");
        return;
    }

    try {
        // API call to the POST /namespaces/{name} endpoint
        await apiCall(`/namespaces/${cleanName}`, 'POST');

        // Elegant success notification
        await showSuccess("Creation Successful", `Namespace <b>${cleanName}</b> has been created.`);

        // Refresh the namespace list to show the new entry in the selector
        await loadNamespaceList();

        // Automatically switch the dashboard context to the new namespace
        updateNamespaceContext(cleanName);

    } catch (err) {
        // Handle API or RBAC errors
        showError("Failed to create namespace: " + err.message);
    }
}

async function loadNamespaceList() {
const container = document.getElementById('nsContextArea');
try {
// Tentiamo di chiamare l'API dei namespace
const response = await apiCall('/namespaces');

if (response && response.can_list) {
// CASO ADMIN: Creiamo la Select
let html = `<select id="nsSelect" onchange="updateNamespaceContext(this.value)" style="min-width: 200px; padding: 8px; border-radius: 8px; border: 1px solid var(--border);">`;
response.items.forEach(ns => {
const selected = ns.name === window.currentNamespace ? 'selected' : '';
html += `<option value="${ns.name}" ${selected}>${ns.name}</option>`;
});
container.innerHTML = html;
} else {
// Se l'API risponde ma dice che non può listare
showManualInput();
}
} catch (err) {
// CASO RESTRICTED (403): Se l'API fallisce del tutto, mostriamo l'input manuale
showManualInput();
}

// In ogni caso, proviamo a caricare la vista corrente
refreshCurrentView();
}

async function loadNodes() {
    currentView = 'nodes';
    const resArea = document.getElementById('resultArea');
    const ns = window.currentNamespace;
    document.getElementById('controlsContainer').style.display = 'none';
    resArea.innerHTML = '<div style="text-align:center; padding:40px;"><i class="fas fa-spinner fa-spin fa-2x"></i></div>';

    try {
        // allSettled: non blocchiamo tutto se una chiamata 403 (profilo limitato)
        const results = await Promise.allSettled([
            apiCall('/cluster/nodes'),
            apiCall('/namespaces'),
            apiCall(`/namespaces/${ns}/deployments`)
        ]);

        const nodes            = results[0].status === 'fulfilled' ? results[0].value : null;
        const namespaces       = results[1].status === 'fulfilled' ? results[1].value : null;
        const deploymentsSample = results[2].status === 'fulfilled' ? results[2].value : null;

        if (!nodes) {
            renderRestrictedAccess();
            return;
        }

        // ── Statistiche aggregate ──────────────────────────────────────────
        const totalCpuCores    = nodes.reduce((acc, n) => acc + (parseInt(n.cpu) || 0), 0);
        const totalCpuAlloc    = nodes.reduce((acc, n) => acc + (parseInt(n.cpu_allocatable) || 0), 0);
        const totalMemKi       = nodes.reduce((acc, n) => acc + (parseInt(n.memory) || 0), 0);
        const totalMemAllocKi  = nodes.reduce((acc, n) => acc + (parseInt(n.mem_allocatable) || 0), 0);
        const readyNodes       = nodes.filter(n => n.status === 'Ready').length;
        const cpuReservedPct   = (((totalCpuCores - totalCpuAlloc) / totalCpuCores) * 100).toFixed(0);
        const memReservedPct   = ((( totalMemKi - totalMemAllocKi) / totalMemKi) * 100).toFixed(0);

        // helper: Ki → GB leggibile
        const kiToGB = ki => (parseInt(ki) / 1024 / 1024).toFixed(1);

        // ── Header ────────────────────────────────────────────────────────
        let html = `
        <div style="display:flex; justify-content:space-between; align-items:flex-end;
                    margin-bottom:25px; border-bottom:2px solid var(--border); padding-bottom:15px;">
            <div>
                <h2 class="page-title">Cluster Overview</h2>
                <p style="margin:5px 0 0; font-size:0.85rem; color:var(--text-muted);">
                    Capacity and schedulable resources across the infrastructure.
                </p>
            </div>
            <span class="badge ${readyNodes === nodes.length ? 'status-running' : 'status-pending'}">
                ${readyNodes} / ${nodes.length} Nodes Ready
            </span>
        </div>

        <!-- ── KPI Cards ─────────────────────────────────────────────── -->
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(175px, 1fr));
                    gap:14px; margin-bottom:30px;">

            <div class="management-card" style="background:var(--card-bg); border:1px solid var(--border);
                 border-radius:14px; padding:18px 20px; border-left:4px solid var(--accent);">
                <div style="font-size:0.62rem; font-weight:800; text-transform:uppercase;
                            letter-spacing:0.1em; color:var(--text-muted); margin-bottom:8px;">
                    Total CPU Capacity
                </div>
                <div style="font-size:1.4rem; font-weight:700; color:var(--text-main);">
                    ${totalCpuCores} <span style="font-size:0.8rem; font-weight:500; color:var(--text-muted);">cores</span>
                </div>
                <div style="font-size:0.72rem; color:var(--text-muted); margin-top:4px;">
                    ${totalCpuAlloc} schedulable &nbsp;·&nbsp;
                    <span style="color:var(--warning);">${cpuReservedPct}% system reserved</span>
                </div>
            </div>

            <div class="management-card" style="background:var(--card-bg); border:1px solid var(--border);
                 border-radius:14px; padding:18px 20px; border-left:4px solid #10b981;">
                <div style="font-size:0.62rem; font-weight:800; text-transform:uppercase;
                            letter-spacing:0.1em; color:var(--text-muted); margin-bottom:8px;">
                    Total RAM Capacity
                </div>
                <div style="font-size:1.4rem; font-weight:700; color:var(--text-main);">
                    ${kiToGB(totalMemKi)} <span style="font-size:0.8rem; font-weight:500; color:var(--text-muted);">GB</span>
                </div>
                <div style="font-size:0.72rem; color:var(--text-muted); margin-top:4px;">
                    ${kiToGB(totalMemAllocKi)} GB schedulable &nbsp;·&nbsp;
                    <span style="color:var(--warning);">${memReservedPct}% system reserved</span>
                </div>
            </div>

            <div class="management-card" style="background:var(--card-bg); border:1px solid var(--border);
                 border-radius:14px; padding:18px 20px; border-left:4px solid var(--warning);">
                <div style="font-size:0.62rem; font-weight:800; text-transform:uppercase;
                            letter-spacing:0.1em; color:var(--text-muted); margin-bottom:8px;">
                    Namespaces
                </div>
                <div style="font-size:1.4rem; font-weight:700; color:var(--text-main);">
                    ${namespaces
                        ? (namespaces.can_list
                            ? namespaces.items.length
                            : '<span style="font-size:0.9rem;">Restricted</span>')
                        : '<i class="fas fa-lock" style="font-size:0.9rem;"></i>'}
                </div>
                <div style="font-size:0.72rem; color:var(--text-muted); margin-top:4px;">
                    ${namespaces?.can_list ? 'visible to this profile' : 'insufficient permissions'}
                </div>
            </div>

            <div class="management-card" style="background:var(--card-bg); border:1px solid var(--border);
                 border-radius:14px; padding:18px 20px; border-left:4px solid #64748b;">
                <div style="font-size:0.62rem; font-weight:800; text-transform:uppercase;
                            letter-spacing:0.1em; color:var(--text-muted); margin-bottom:8px;">
                    Deployments (${ns})
                </div>
                <div style="font-size:1.4rem; font-weight:700; color:var(--text-main);">
                    ${deploymentsSample !== null
                        ? deploymentsSample.length
                        : '<i class="fas fa-lock" style="font-size:0.9rem;"></i>'}
                </div>
                <div style="font-size:0.72rem; color:var(--text-muted); margin-top:4px;">
                    ${deploymentsSample !== null
                        ? `${deploymentsSample.filter(d => d.replicas_ready === d.replicas_desired).length} healthy`
                        : 'insufficient permissions'}
                </div>
            </div>
        </div>

        <!-- ── Node Table ─────────────────────────────────────────────── -->
        <h3 style="font-size:0.85rem; font-weight:800; text-transform:uppercase;
                   letter-spacing:0.1em; color:var(--text-muted); margin-bottom:14px;">
            <i class="fas fa-server" style="margin-right:8px; color:var(--accent);"></i>Node Distribution
        </h3>
        <table class="data-table">
            <thead>
                <tr>
                    <th>Node</th>
                    <th>Status</th>
                    <th>K8s Version</th>
                    <th>CPU Capacity</th>
                    <th>RAM Capacity</th>
                    <th>Since</th>
                </tr>
            </thead>
            <tbody>`;

        nodes.forEach(n => {
            const isReady       = n.status === 'Ready';
            const memTotGB      = kiToGB(n.memory);
            const memAllocGB    = kiToGB(n.mem_allocatable);
            const cpuTotal      = parseInt(n.cpu) || 0;
            const cpuAlloc      = parseInt(n.cpu_allocatable) || 0;
            // % schedulable rispetto al totale (quanto è disponibile per i Pod)
            const cpuSchedPct   = cpuTotal ? ((cpuAlloc / cpuTotal) * 100).toFixed(0) : 0;
            const memSchedPct   = parseFloat(memTotGB)
                                    ? ((parseFloat(memAllocGB) / parseFloat(memTotGB)) * 100).toFixed(0)
                                    : 0;

            // Uptime approssimativo dalla creation_timestamp
            let uptime = '—';
            if (n.creation_timestamp) {
                const days = Math.floor((Date.now() - new Date(n.creation_timestamp)) / 86400000);
                uptime = days === 0 ? 'Today' : `${days}d`;
            }

            html += `
                <tr>
                    <td>
                        <div style="font-weight:700; color:var(--accent); font-size:0.9rem;">${n.name}</div>
                        <div style="font-size:0.72rem; color:var(--text-muted); margin-top:2px;">
                            ${n.os} &nbsp;·&nbsp; ${n.role}
                        </div>
                    </td>
                    <td>
                        <span class="badge ${isReady ? 'status-running' : 'status-pending'}">${n.status}</span>
                    </td>
                    <td>
                        <code style="font-size:0.78rem; background:#f1f5f9;
                              padding:3px 8px; border-radius:6px;">${n.version}</code>
                    </td>
                    <td style="width:160px;">
                        <div style="display:flex; justify-content:space-between;
                                    font-size:0.72rem; margin-bottom:5px;">
                            <span style="color:var(--text-muted);">
                                <b style="color:var(--text-main);">${cpuAlloc}</b> / ${cpuTotal} cores schedulable
                            </span>
                            <span style="color:var(--accent); font-weight:600;">${cpuSchedPct}%</span>
                        </div>
                        <div style="width:100%; height:5px; background:#e2e8f0;
                                    border-radius:10px; overflow:hidden;">
                            <div style="width:${cpuSchedPct}%; height:100%;
                                        background:var(--accent); border-radius:10px;"></div>
                        </div>
                    </td>
                    <td style="width:160px;">
                        <div style="display:flex; justify-content:space-between;
                                    font-size:0.72rem; margin-bottom:5px;">
                            <span style="color:var(--text-muted);">
                                <b style="color:var(--text-main);">${memAllocGB}</b> / ${memTotGB} GB schedulable
                            </span>
                            <span style="color:#10b981; font-weight:600;">${memSchedPct}%</span>
                        </div>
                        <div style="width:100%; height:5px; background:#e2e8f0;
                                    border-radius:10px; overflow:hidden;">
                            <div style="width:${memSchedPct}%; height:100%;
                                        background:#10b981; border-radius:10px;"></div>
                        </div>
                    </td>
                    <td style="font-size:0.78rem; color:var(--text-muted);">${uptime}</td>
                </tr>`;
        });

        html += `</tbody></table>

        <!-- ── Nota informativa ──────────────────────────────────────── -->
        <div style="margin-top:16px; padding:12px 16px; background:#f8fafd;
                    border:1px solid var(--border); border-radius:10px;
                    font-size:0.75rem; color:var(--text-muted); display:flex; align-items:center; gap:10px;">
            <i class="fas fa-info-circle" style="color:var(--accent); flex-shrink:0;"></i>
            <span>
                <b>Schedulable</b> = capacity minus resources reserved by the OS and Kubernetes system components (kubelet, kube-proxy, etc.).
                These bars show how much of each node is available for Pod scheduling — not real-time utilization.
            </span>
        </div>`;

        resArea.innerHTML = html;

    } catch (err) {
        showError("Failed to load nodes: " + err.message);
    }
}

async function loadNamespace() {
    currentView = 'namespaces';
    const resArea = document.getElementById('resultArea');
    
    // Nascondiamo i controlli superiori se presenti, per evitare confusione
    const controls = document.getElementById('controlsContainer');
    if (controls) controls.style.display = 'none';

    resArea.innerHTML = '<div style="text-align:center; padding:40px;"><i class="fas fa-spinner fa-spin fa-2x"></i></div>';

    try {
        const response = await apiCall('/namespaces');
        
        // Verifichiamo se l'utente ha i permessi per listare (can_list)
        if (!response || !response.can_list) {
            renderRestrictedAccess();
            return;
        }

        const data = response.items || [];

        let html = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; border-bottom:2px solid var(--border); padding-bottom:15px;">
                <div>
                    <h2 class="page-title">Cluster Namespaces</h2>
                    <p style="margin:5px 0 0; font-size:0.85rem; color:var(--text-muted);">
                        Virtual clusters used to isolate groups of resources.
                    </p>
                </div>
                <button onclick="addNewNamespace()" class="btn-action" style="display:flex; align-items:center; gap:8px;">
                    <i class="fas fa-plus-circle"></i> Create Namespace
                </button>
            </div>
            
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Namespace Name</th>
                        <th>Status</th>
                        <th>Creation Date</th>
                        <th style="text-align:right">Actions</th>
                    </tr>
                </thead>
                <tbody>`;

        data.forEach(ns => {
            const isActive = ns.status === 'Active';
            const statusClass = isActive ? 'status-running' : 'status-pending';
            
            html += `
                <tr>
                    <td>
                        <div style="display:flex; align-items:center; gap:10px;">
                            <i class="fas fa-box" style="color:var(--accent); font-size:0.9rem;"></i>
                            <b style="font-size:0.95rem;">${ns.name}</b>
                            ${ns.name === 'default' ? '<small style="color:var(--text-muted); font-style:italic;">(system default)</small>' : ''}
                        </div>
                    </td>
                    <td>
                        <span class="badge ${statusClass}">${ns.status}</span>
                    </td>
                    <td>
                        <small style="color:var(--text-muted)">
                            <i class="far fa-calendar-alt" style="margin-right:5px;"></i>
                            ${ns.creation_timestamp ? new Date(ns.creation_timestamp).toLocaleString() : 'N/A'}
                        </small>
                    </td>
                    <td style="text-align:right">
                        <button onclick="deleteNamespace('${ns.name}')" 
                                class="btn-small delete-btn" 
                                title="Delete Namespace"
                                ${ns.name === 'default' || ns.name === 'kube-system' || ns.name === 'kube-node-lease' || ns.name === 'kube-flannel' || ns.name === 'kube-public' ? 'disabled style="opacity:0.3; cursor:not-allowed;"' : ''}>
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>`;
        });

        resArea.innerHTML = data.length > 0 
            ? html + '</tbody></table>' 
            : `<div style="text-align:center; padding:40px; color:var(--text-muted);">No namespaces found.</div>`;

    } catch (err) {
        if (err.message === "RESTRICTED") {
            renderRestrictedAccess();
        } else {
            showError("Failed to load namespaces: " + err.message);
        }
    }
}

async function loadPV() {
    currentView = 'pv';
    const resArea = document.getElementById('resultArea');
    
    // Nascondiamo la barra dei namespace perché i PV sono globali
    const controls = document.getElementById('controlsContainer');
    if (controls) controls.style.display = 'none';

    resArea.innerHTML = '<div style="text-align:center; padding:40px;"><i class="fas fa-spinner fa-spin fa-2x"></i></div>';

    try {
        const data = await apiCall('/cluster/volumes');
        let html = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
                <h2 class="page-title"">Persistent Volumes (Global)</h2>
            </div>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Capacity</th>
                        <th>Status</th>
                        <th>Claim (NS/Name)</th>
                        <th>Storage Class</th>
                    </tr>
                </thead>
                <tbody>`;

        data.forEach(pv => {
            const statusClass = pv.status === 'Bound' ? 'status-running' : 'status-pending';
            html += `
                <tr>
                    <td><b>${pv.name}</b></td>
                    <td><code style="background:#f1f5f9; padding:2px 5px; border-radius:4px;">${pv.capacity}</code></td>
                    <td><span class="badge ${statusClass}">${pv.status}</span></td>
                    <td><small style="color:var(--text-muted)">${pv.claim}</small></td>
                    <td><small>${pv.storage_class || 'standard'}</small></td>
                </tr>`;
        });
        resArea.innerHTML = data.length > 0 ? html + '</tbody></table>' : `<p style="text-align:center; margin-top:20px; color:var(--text-muted);">No Persistent Volumes found.</p>`;;
    } catch (err) {
        if (err.message === "RESTRICTED") {
            renderRestrictedAccess();
        } else {
            showError("Failed to load PV: " + err.message);
        }
    }
}

async function loadPVC() {
    currentView = 'pvc';
    const ns = window.currentNamespace;
    const resArea = document.getElementById('resultArea');
    
    // Riactiviamo i controlli perché qui il namespace conta
    const controls = document.getElementById('controlsContainer');
    if (controls) controls.style.display = 'flex';

    resArea.innerHTML = '<div style="text-align:center; padding:40px;"><i class="fas fa-spinner fa-spin fa-2x"></i></div>';

    try {
        const data = await apiCall(`/namespaces/${ns}/pvc`);
        let html = `<h2>Volume Claims [${ns}]</h2>
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>Name</th>
                                <th>Status</th>
                                <th>Volume</th>
                                <th>Capacity</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>`;

        data.forEach(pvc => {
            const statusClass = pvc.status === 'Bound' ? 'status-running' : 'status-pending';
            html += `
                <tr>
                    <td><b>${pvc.name}</b></td>
                    <td><span class="badge ${statusClass}">${pvc.status}</span></td>
                    <td><small style="font-family:monospace;">${pvc.volume || '-'}</small></td>
                    <td>${pvc.capacity}</td>
                    <td>
                        <button onclick="deleteResource('pvc', '${pvc.name}')" class="btn-small delete-btn">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>`;
        });
        resArea.innerHTML = data.length > 0 ? html + '</tbody></table>' : `<p style="text-align:center; margin-top:20px; color:var(--text-muted);">No PVC found in namespace ${ns}.</p>`;;
    } catch (err) {
        if (err.message === "RESTRICTED") {
            renderRestrictedAccess();
        } else {
            showError("Failed to load PVC: " + err.message);
        }
    }
}

async function loadStorageClasses() {
    currentView = 'storageclasses';
    const resArea = document.getElementById('resultArea');
    
    // Nascondiamo i controlli perché la risorsa è globale
    document.getElementById('controlsContainer').style.display = 'none';

    resArea.innerHTML = '<div style="text-align:center; padding:40px;"><i class="fas fa-spinner fa-spin fa-2x"></i></div>';

    try {
        const data = await apiCall('/cluster/storage-classes');
        
        let html = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                <h2 class="page-title">Storage Classes</h2>
                <small style="color:var(--text-muted)">Global Cluster Resources</small>
            </div>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Provisioner</th>
                        <th>Reclaim Policy</th>
                        <th>Binding Mode</th>
                        <th>Creation Date</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>`;

        if (!data || data.length === 0) {
            html += `<tr><td colspan="5" style="text-align:center; padding:30px; color:var(--text-muted);">No Storage Classes defined in the cluster.</td></tr>`;
        } else {
            data.forEach(sc => {
                html += `
                    <tr>
                        <td><b style="color:var(--accent)">${sc.name}</b></td>
                        <td><code style="font-size:0.75rem">${sc.provisioner}</code></td>
                        <td><span class="badge" style="background:#f1f5f9; color:#475569;">${sc.reclaim_policy}</span></td>
                        <td><small>${sc.volume_binding_mode}</small></td>
                        <td><small>${new Date(sc.age).toLocaleDateString()}</small></td>
                        <td><button onclick="deleteStorageClass('${sc.name}')" class="btn-small delete-btn">
                            <i class="fas fa-trash"></i>
                        </button></td>
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

async function deleteStorageClass(name) {
    // 1. Usiamo showConfirm invece del confirm nativo
    // Passiamo true come terzo parametro (isDanger) per attivare lo stile rosso
    const confirmed = await showConfirm(
        "Delete StorageClass", 
        `Warning: Are you sure you want to delete '${name}'? This will prevent the creation of new volumes based on this profile.`,
        true 
    );

    if (!confirmed) return;

    try {
        // Chiamata API
        await apiCall(`/cluster/storage-classes/${name}`, 'DELETE');

        // 2. Usiamo showSuccess invece dell'alert nativo
        showSuccess(`StorageClass '${name}' deleted successfully.`);

        // 3. Ricarichiamo la tabella (modifica il nome se la funzione è diversa)
        if (typeof loadStorageClasses === "function") {
            loadStorageClasses();
        }
    } catch (err) {
        // 4. Usiamo showError per gestire il fallimento
        showError("Failed to delete StorageClass: " + (err.message || err));
    }
}

