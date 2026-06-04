async function loadConfigMaps() {
    currentView = 'configmaps';
    renderLabelFilter(true);
    
    const ns = window.currentNamespace;
    const resArea = document.getElementById('resultArea');
    
    const labelSelector = document.getElementById('labelFilter')?.value || '';
    let url = `/namespaces/${ns}/configmaps`;
    if (labelSelector) url += `?label_selector=${encodeURIComponent(labelSelector)}`;

    resArea.innerHTML = '<div style="text-align:center; padding:20px;"><i class="fas fa-spinner fa-spin fa-2x"></i></div>';

    try {
        const data = await apiCall(url);
        let html = `
            <h2>ConfigMaps [${ns}]</h2>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Labels</th>
                        <th>Data Keys</th>
                        <th style="text-align:right">Actions</th>
                    </tr>
                </thead>
                <tbody>`;
        
        data.forEach(cm => {
            const keysHtml = cm.keys.length > 0 
                ? cm.keys.map(k => `<code class="key-badge">${k}</code>`).join('')
                : '<span class="none-text">No data</span>';

            html += `
                <tr>
                    <td><b>${cm.name}</b></td>
                    <td>${renderLabels(cm.labels)}</td>
                    <td>${keysHtml}</td>
                    <td style="text-align:right">
                        <button onclick="deleteResource('configmaps', '${cm.name}')" class="btn-small delete-btn" title="Delete">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>`;
        });

        resArea.innerHTML = data.length > 0 
            ? html + '</tbody></table>' 
            : `<p style="text-align:center; margin-top:20px; color:var(--text-muted);">No ConfigMap found in namespace ${ns}.</p>`;

    } catch (err) {
        if (err.message === "RESTRICTED") {
            renderRestrictedAccess(); 
        } else {
            showError(err.message);
        }
    }
}

async function loadSecrets() {
    currentView = 'secrets';
    renderLabelFilter(true);
    
    const ns = window.currentNamespace;
    const resArea = document.getElementById('resultArea');
    
    const labelSelector = document.getElementById('labelFilter')?.value || '';
    let url = `/namespaces/${ns}/secrets`;
    if (labelSelector) url += `?label_selector=${encodeURIComponent(labelSelector)}`;

    resArea.innerHTML = '<div style="text-align:center; padding:20px;"><i class="fas fa-spinner fa-spin fa-2x"></i></div>';

    try {
        const data = await apiCall(url);
        let html = `
            <h2>Secrets [${ns}]</h2>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Labels</th>
                        <th>Type</th>
                        <th>Data Keys</th>
                        <th style="text-align:right">Actions</th>
                    </tr>
                </thead>
                <tbody>`;
        
        data.forEach(s => {
            const keysHtml = s.keys.length > 0 
                ? s.keys.map(k => `<span class="key-badge-secret"><i class="fas fa-lock"></i>${k}</span>`).join('')
                : '<span class="none-text">Empty</span>';

            html += `
                <tr>
                    <td><b>${s.name}</b></td>
                    <td>${renderLabels(s.labels)}</td>
                    <td><small class="type-tag">${s.type}</small></td>
                    <td>${keysHtml}</td>
                    <td style="text-align:right">
                        <button onclick="deleteResource('secrets', '${s.name}')" class="btn-small delete-btn" title="Delete">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>`;
        });

        resArea.innerHTML = data.length > 0 
            ? html + '</tbody></table>' 
            : `<p style="text-align:center; margin-top:20px; color:var(--text-muted);">No Secret found in namespace ${ns}.</p>`;

    } catch (err) {
        if (err.message === "RESTRICTED") {
            renderRestrictedAccess(); 
        } else {
            showError(err.message);
        }
    }
}

async function loadServices() {
    currentView = 'services';
    renderLabelFilter(true);
    
    const ns = window.currentNamespace;
    const resArea = document.getElementById('resultArea');
    
    const labelSelector = document.getElementById('labelFilter')?.value || '';
    let url = `/namespaces/${ns}/services`;
    if (labelSelector) url += `?label_selector=${encodeURIComponent(labelSelector)}`;

    resArea.innerHTML = '<div style="text-align:center; padding:20px;"><i class="fas fa-spinner fa-spin fa-2x"></i></div>';

    try {
        const data = await apiCall(url);
        let html = `
            <h2>Services [${ns}]</h2>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Labels</th>
                        <th>Type</th>
                        <th>Cluster IP</th>
                        <th style="text-align:right">Actions</th>
                    </tr>
                </thead>
                <tbody>`;
        
        data.forEach(s => {
            html += `
                <tr onclick="inspectResource('services', '${s.name}')" class="clickable-row">
                    <td><b class="resource-name">${s.name}</b></td>
                    <td>${renderLabels(s.labels)}</td>
                    <td><span class="badge" style="background:#f1f5f9; color:#475569; font-weight:500;">${s.type}</span></td>
                    <td><code style="font-size:0.75rem">${s.cluster_ip || 'N/A'}</code></td>
                    <td style="text-align:right" onclick="event.stopPropagation()">
                        <button onclick="deleteResource('services', '${s.name}')" class="btn-small delete-btn" title="Delete">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>`;
        });

        resArea.innerHTML = data.length > 0 
            ? html + '</tbody></table>' 
            : `<p style="text-align:center; margin-top:20px; color:var(--text-muted);">No Service found in namespace ${ns}.</p>`;
            
    } catch (err) { 
        if (err.message === "RESTRICTED") {
            renderRestrictedAccess(); 
        } else {
            showError(err.message);
        }
    }
}


async function loadIngress() {
    window.currentView = 'ingress';
    
    // 1. Forza il rendering del filtro (Fix per il bug della sparizione)
    renderLabelFilter(true);
    
    const ns = window.currentNamespace;
    const resArea = document.getElementById('resultArea');
    
    // 2. Recupero il valore del filtro per la chiamata API
    const labelSelector = document.getElementById('labelFilter')?.value || '';
    let url = `/namespaces/${ns}/ingress`;
    if (labelSelector) url += `?label_selector=${encodeURIComponent(labelSelector)}`;

    resArea.innerHTML = '<div style="text-align:center; padding:20px;"><i class="fas fa-spinner fa-spin fa-2x"></i></div>';

    try {
        const data = await apiCall(url);
        
        let html = `
            <h2>Ingress Resources [${ns}]</h2>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Labels</th>
                        <th>Hosts</th>
                        <th>Address (LB)</th>
                        <th>Age</th>
                        <th style="text-align:right">Actions</th>
                    </tr>
                </thead>
                <tbody>`;

        data.forEach(ing => {
            // Render Host con stile badge coerente
            const hostsHtml = ing.hosts.length > 0 
                ? ing.hosts.map(h => `<code class="key-badge" style="color:var(--accent);">${h}</code>`).join(' ')
                : '<span class="none-text">*</span>';

            // Render IP/Hostname esterni
            const addrHtml = ing.address.length > 0
                ? ing.address.map(a => `<span class="type-tag" style="font-size:0.7rem;">${a}</span>`).join(', ')
                : '<span class="none-text">-</span>';

            html += `
                <tr>
                    <td><b style="color:var(--accent)">${ing.name}</b></td>
                    <td>${renderLabels(ing.labels)}</td>
                    <td>${hostsHtml}</td>
                    <td>${addrHtml}</td>
                    <td><small>${new Date(ing.creation_timestamp).toLocaleDateString()}</small></td>
                    <td style="text-align:right">
                        <button onclick="deleteResource('ingress', '${ing.name}')" class="btn-small delete-btn" title="Delete Ingress">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>`;
        });

        resArea.innerHTML = data.length > 0 
            ? html + '</tbody></table>' 
            : `<p style="text-align:center; margin-top:20px; color:var(--text-muted);">No Ingress found in namespace ${ns}.</p>`;

    } catch (err) { 
        if (err.message === "RESTRICTED") {
            renderRestrictedAccess(); 
        } else {
            showError(err.message);
        } 
    }
}

// =============================================================================
// NETWORK POLICIES
// =============================================================================

async function loadNetworkPolicies() {
    currentView = 'networkpolicies';
    renderLabelFilter(true);

    const ns = window.currentNamespace;
    const resArea = document.getElementById('resultArea');

    const labelSelector = document.getElementById('labelFilter')?.value || '';
    let url = `/namespaces/${ns}/networkpolicies`;
    if (labelSelector) url += `?label_selector=${encodeURIComponent(labelSelector)}`;

    resArea.innerHTML = '<div style="text-align:center; padding:20px;"><i class="fas fa-spinner fa-spin fa-2x"></i></div>';

    try {
        const data = await apiCall(url);

        let html = `
            <h2>Network Policies [${ns}]</h2>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Labels</th>
                        <th>Pod Selector</th>
                        <th>Policy Types</th>
                        <th>Ingress Rules</th>
                        <th>Egress Rules</th>
                        <th style="text-align:right">Actions</th>
                    </tr>
                </thead>
                <tbody>`;

        if (!data || data.length === 0) {
            html += `<tr><td colspan="7" style="text-align:center; padding:30px; color:var(--text-muted);">No NetworkPolicy found in namespace ${ns}.</td></tr>`;
        } else {
            data.forEach(np => {
                const podSelectorHtml = np.pod_selector && Object.keys(np.pod_selector).length > 0
                    ? Object.entries(np.pod_selector).map(([k, v]) => `<code style="font-size:0.7rem">${k}=${v}</code>`).join(' ')
                    : '<span style="color:var(--text-muted); font-size:0.75rem;">All pods</span>';

                const typesHtml = (np.policy_types || []).map(t =>
                    `<span style="font-size:0.7rem; background:#e0f2fe; color:#0369a1; padding:2px 6px; border-radius:4px; font-weight:600;">${t}</span>`
                ).join(' ');

                html += `
                    <tr>
                        <td><b class="resource-name">${np.name}</b></td>
                        <td>${renderLabels(np.labels)}</td>
                        <td>${podSelectorHtml}</td>
                        <td>${typesHtml || '<span style="color:var(--text-muted)">—</span>'}</td>
                        <td>${np.ingress_rules}</td>
                        <td>${np.egress_rules}</td>
                        <td style="text-align:right; white-space:nowrap;">
                            <button onclick="deleteResource('networkpolicies', '${np.name}')" class="btn-small delete-btn" title="Delete NetworkPolicy">
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



