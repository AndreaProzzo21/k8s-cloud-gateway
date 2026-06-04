async function loadServiceAccounts() {
    currentView = 'serviceaccounts';
    renderLabelFilter(false);
    const ns = window.currentNamespace;
    const resArea = document.getElementById('resultArea');
    try {
        const data = await apiCall(`/namespaces/${ns}/serviceaccounts`);
        let html = `<h2>Service Accounts [${ns}]</h2><table class="data-table">
                    <thead><tr><th>Name</th><th>Secrets</th><th style="text-align:right">Actions</th></tr></thead><tbody>`;
        
        data.forEach(sa => {
            html += `<tr>
                <td><b>${sa.name}</b></td>
                <td><span class="badge" style="background:#e0f2fe; color:#0369a1;">${sa.secrets} Secret(s)</span></td>
                <td style="text-align:right">
                    <button onclick="deleteResource('serviceaccounts', '${sa.name}')" class="btn-small delete-btn"><i class="fas fa-trash"></i></button>
                </td>
            </tr>`;
        });
        
        resArea.innerHTML = data.length > 0 
            ? html + '</tbody></table>' 
            : `<p style="text-align:center; margin-top:20px; color:var(--text-muted);">No Service Accounts found in namespace ${ns}.</p>`;

    } catch (err) {                
        if (err.message === "RESTRICTED") {
            renderRestrictedAccess(); 
        } else {
            showError(err.message);
        }
    }
}

async function loadRoles() {
    currentView = 'roles';
    renderLabelFilter(false);
    const ns = window.currentNamespace;
    const resArea = document.getElementById('resultArea');
    try {
        const data = await apiCall(`/namespaces/${ns}/roles`);
        let html = `<h2>Roles [${ns}]</h2><table class="data-table">
                    <thead><tr><th>Name</th><th>Permissions</th><th style="text-align:right">Actions</th></tr></thead><tbody>`;
        
        data.forEach(r => {
            html += `<tr>
                <td><b>${r.name}</b></td>
                <td><span class="badge" style="background:#f1f5f9; color:#475569;">${r.rules} Rules</span></td>
                <td style="text-align:right">
                    <button onclick="deleteResource('roles', '${r.name}')" class="btn-small delete-btn"><i class="fas fa-trash"></i></button>
                </td>
            </tr>`;
        });
        
        resArea.innerHTML = data.length > 0 
            ? html + '</tbody></table>' 
            : `<p style="text-align:center; margin-top:20px; color:var(--text-muted);">No Roles found in namespace ${ns}.</p>`;

    } catch (err) {                
        if (err.message === "RESTRICTED") {
            renderRestrictedAccess(); 
        } else {
            showError(err.message);
        }}
}

async function loadRoleBindings() {
    currentView = 'rolebindings';
    renderLabelFilter(false);
    const ns = window.currentNamespace;
    const resArea = document.getElementById('resultArea');
    try {
        const data = await apiCall(`/namespaces/${ns}/rolebindings`);
        let html = `<h2>Role Bindings [${ns}]</h2><table class="data-table">
                    <thead><tr><th>Name</th><th>Role Ref</th><th>Subjects</th><th style="text-align:right">Actions</th></tr></thead><tbody>`;
        
        data.forEach(rb => {
            const subCount = rb.subjects ? rb.subjects.length : 0;
            html += `<tr>
                <td><b>${rb.name}</b></td>
                <td><code style="color:var(--accent)">${rb.role_ref}</code></td>
                <td><span class="badge" style="background:#f0fdf4; color:#166534;">${subCount} Subject(s)</span></td>
                <td style="text-align:right">
                    <button onclick="deleteResource('rolebindings', '${rb.name}')" class="btn-small delete-btn"><i class="fas fa-trash"></i></button>
                </td>
            </tr>`;
        });
        
        resArea.innerHTML = data.length > 0 
            ? html + '</tbody></table>' 
            : `<p style="text-align:center; margin-top:20px; color:var(--text-muted);">No Role Bindings found in namespace ${ns}.</p>`;

    } catch (err) {                 
        if (err.message === "RESTRICTED") {
            renderRestrictedAccess(); 
        } else {
            showError(err.message);
        } 
    }
}


// =============================================================================
// CLUSTER ROLES  (cluster-wide: niente namespace nella URL)
// =============================================================================
async function loadClusterRoles() {
    currentView = 'clusterroles';
    const resArea = document.getElementById('resultArea');
    
    // Nascondiamo i controlli superiori (namespace/label) per le risorse cluster-wide
    const controls = document.getElementById('controlsContainer');
    if (controls) controls.style.display = 'none';

    resArea.innerHTML = '<div style="text-align:center; padding:40px;"><i class="fas fa-spinner fa-spin fa-2x"></i></div>';

    try {
        const data = await apiCall('/cluster/clusterroles');

        let html = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; border-bottom:2px solid var(--border); padding-bottom:15px;">
                <div>
                    <h2 class="page-title">Cluster Roles</h2>
                    <p style="margin:5px 0 0; font-size:0.85rem; color:var(--text-muted);">
                        Cluster-wide permission sets that can be assigned to users or service accounts.
                    </p>
                </div>
            </div>
            
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Permissions</th>
                        <th style="text-align:right">Actions</th>
                    </tr>
                </thead>
                <tbody>`;

        data.forEach(cr => {
            html += `
                <tr>
                    <td>
                        <div style="display:flex; align-items:center; gap:10px;">
                            <i class="fas fa-user-shield" style="color:var(--accent); font-size:0.9rem;"></i>
                            <b>${cr.name}</b>
                        </div>
                    </td>
                    <td><span class="badge" style="background:#f1f5f9; color:#475569;">${cr.rules} Rules</span></td>
                    <td style="text-align:right">
                        <button onclick="deleteClusterResource('clusterroles', '${cr.name}')" class="btn-small delete-btn" title="Delete ClusterRole">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>`;
        });

        resArea.innerHTML = data.length > 0
            ? html + '</tbody></table>'
            : `<div style="text-align:center; padding:40px; color:var(--text-muted);">No Cluster Roles found.</div>`;

    } catch (err) {
        if (err.message === 'RESTRICTED') {
            renderRestrictedAccess();
        } else {
            showError("Failed to load Cluster Roles: " + err.message);
        }
    }
}

// =============================================================================
// CLUSTER ROLE BINDINGS  (cluster-wide: niente namespace nella URL)
// =============================================================================
async function loadClusterRoleBindings() {
    currentView = 'clusterrolebindings';
    const resArea = document.getElementById('resultArea');
    
    // Nascondiamo i controlli superiori
    const controls = document.getElementById('controlsContainer');
    if (controls) controls.style.display = 'none';

    resArea.innerHTML = '<div style="text-align:center; padding:40px;"><i class="fas fa-spinner fa-spin fa-2x"></i></div>';

    try {
        const data = await apiCall('/cluster/clusterrolebindings');

        let html = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; border-bottom:2px solid var(--border); padding-bottom:15px;">
                <div>
                    <h2 class="page-title">Cluster Role Bindings</h2>
                    <p style="margin:5px 0 0; font-size:0.85rem; color:var(--text-muted);">
                        Grants ClusterRole permissions to subjects across the entire cluster.
                    </p>
                </div>
            </div>
            
            <table class="data-table" style="table-layout:fixed; width:100%;">
                <thead>
                    <tr>
                        <th style="width:45%">Name</th>
                        <th style="width:40%">Role Ref</th>
                        <th style="width:15%; text-align:right">Actions</th>
                    </tr>
                </thead>
                <tbody>`;

        data.forEach(crb => {
            const subCount = crb.subjects ? crb.subjects.length : 0;
            html += `
                <tr>
                    <td style="max-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${crb.name}">
                        <div style="display:flex; align-items:center; gap:10px;">
                            <i class="fas fa-link" style="color:var(--accent); font-size:0.9rem;"></i>
                            <b>${crb.name}</b>
                        </div>
                    </td>
                    <td style="max-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${crb.role_ref}">
                        <code style="color:var(--accent)">${crb.role_ref}</code>
                        <span class="badge" style="background:#f0fdf4; color:#166534; margin-left:6px;">${subCount} Subject(s)</span>
                    </td>
                    <td style="text-align:right">
                        <button onclick="deleteClusterResource('clusterrolebindings', '${crb.name}')" class="btn-small delete-btn" title="Delete ClusterRoleBinding">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>`;
        });

        resArea.innerHTML = data.length > 0
            ? html + '</tbody></table>'
            : `<div style="text-align:center; padding:40px; color:var(--text-muted);">No Cluster Role Bindings found.</div>`;

    } catch (err) {
        if (err.message === 'RESTRICTED') {
            renderRestrictedAccess();
        } else {
            showError("Failed to load Cluster Role Bindings: " + err.message);
        }
    }
}