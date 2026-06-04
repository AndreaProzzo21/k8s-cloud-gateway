function renderLoadingOverlay(show = true, message = "Initializing cluster...") {
    let overlay = document.getElementById('loadingOverlay');

    if (show) {
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'loadingOverlay';
            // Overlay fullscreen semi-trasparente
            overlay.style.cssText = `
                position: fixed; inset: 0; z-index: 9999;
                background: rgba(0,0,0,0.55);
                display: flex; align-items: center; justify-content: center;
                transition: opacity 0.3s ease;
            `;
            document.body.appendChild(overlay);
        }
        overlay.classList.remove('hidden');
        overlay.innerHTML = `
            <div id="loaderContent" style="
                background: var(--color-background-primary, #fff);
                border-radius: 12px;
                border: 0.5px solid rgba(0,0,0,0.1);
                padding: 2.5rem 2rem;
                max-width: 400px; width: 90%;
                text-align: center;
            ">
                <div class="minimal-spinner" style="margin: 0 auto 1.5rem;"></div>
                <p style="font-size: 11px; font-weight: 600; letter-spacing: 2px;
                          color: #94a3b8; margin: 0 0 8px; text-transform: uppercase;">
                    Kubernetes Cloud Gateway
                </p>
                <h3 style="font-size: 16px; font-weight: 500; color: #1e293b; margin: 0;">
                    ${message}
                </h3>
            </div>
        `;
    } else if (overlay) {
        overlay.style.opacity = '0';
        setTimeout(() => overlay.remove(), 300);
    }
}

function handleLoadingError(errorMsg) {
    const content = document.getElementById('loaderContent');
    if (!content) return;

    content.innerHTML = `
        <div style="width:1px; height:3px; background:#ef4444; margin:0 auto 2rem; 
                    box-shadow: 0 0 0 0 rgba(239,68,68,0); 
                    animation: pulseBar 1.8s ease-out forwards;">
        </div>
        <style>
            @keyframes pulseBar {
                0%   { width:1px;   opacity:1; }
                60%  { width:120px; opacity:1; }
                100% { width:120px; opacity:0.35; }
            }
        </style>

        <p style="font-size:10px; font-weight:700; letter-spacing:3px; 
                  color:#ef4444; margin:0 0 12px; text-transform:uppercase;">
            Connection failed
        </p>

        <h2 style="font-size:20px; font-weight:500; color:#1e293b; 
                   margin:0 0 8px; letter-spacing:-0.3px;">
            Cluster unreachable
        </h2>

        <p style="font-size:13px; color:#94a3b8; line-height:1.7; 
                  margin:0 0 2rem; max-width:280px; margin-left:auto; margin-right:auto;">
            ${errorMsg || "The host may be powered off or the cluster is not responding."}
        </p>

        <div style="width:100%; height:1px; background:#f1f5f9; margin:0 0 1.5rem;"></div>

        <div style="display:flex; gap:10px; justify-content:center;">
            <button onclick="location.reload()" style="
                display:flex; align-items:center; gap:7px;
                padding:9px 22px; border-radius:8px;
                border:1px solid #e2e8f0; background:#fff;
                color:#1e293b; font-size:13px; font-weight:500;
                cursor:pointer; transition:background 0.15s;
            " onmouseover="this.style.background='#f8fafc'" 
               onmouseout="this.style.background='#fff'">
                <i class="fas fa-redo" style="font-size:12px; color:#94a3b8;"></i> Retry
            </button>
            <button onclick="logout()" style="
                display:flex; align-items:center; gap:7px;
                padding:9px 22px; border-radius:8px;
                border:1px solid #fecaca; background:#fff5f5;
                color:#ef4444; font-size:13px; font-weight:500;
                cursor:pointer; transition:background 0.15s;
            " onmouseover="this.style.background='#fee2e2'"
               onmouseout="this.style.background='#fff5f5'">
                <i class="fas fa-sign-out-alt" style="font-size:12px;"></i> Logout
            </button>
        </div>
    `;
}


function renderRestrictedAccess() {
    const resArea = document.getElementById('resultArea');
    
    resArea.innerHTML = `
        <div style="
            display: flex; 
            align-items: center; 
            justify-content: center; 
            height: 100%; 
            min-height: 450px;
            padding: 20px;
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            animation: fadeIn 0.5s cubic-bezier(0.4, 0, 0.2, 1);
        ">
            <div style="
                background: #ffffff; 
                padding: 50px 40px; 
                border-radius: 24px; 
                border: 1px solid rgba(0,0,0,0.04);
                box-shadow: 0 10px 30px rgba(0,0,0,0.02);
                text-align: center;
                max-width: 480px;
                width: 100%;
            ">
                <div style="
                    background: #fff5f5;
                    width: 64px;
                    height: 64px;
                    border-radius: 20px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin: 0 auto 24px;
                ">
                    <i class="fas fa-lock" style="font-size: 1.5rem; color: #ffa968;"></i>
                </div>
                
                <h2 style="
                    color: #1a202c; 
                    font-size: 1.3rem; 
                    font-weight: 600; 
                    margin-bottom: 16px;
                    letter-spacing: -0.02em;
                ">
                    Access Restricted
                </h2>
                
                <p style="
                    font-size: 0.95rem; 
                    line-height: 1.7; 
                    margin-bottom: 0;
                    color: #4a5568;
                    font-weight: 400;
                ">
                    Your current profile lacks the necessary <strong>RBAC permissions</strong> to interact with 
                    <span style="
                        color: #4a5568; 
                        background: #edf2f7; 
                        padding: 2px 8px; 
                        border-radius: 6px; 
                        font-weight: 600;
                        font-size: 0.85rem;
                    ">
                        ${window.currentView.toUpperCase()}
                    </span> 
                    on this cluster.
                </p>

            </div>
        </div>`;
}


function setActive(el) {
    if (!el) return;
    
    // Check di sicurezza: se l'utente è restricted e prova ad accedere ai nodi
    if (window.userProfile === 'restricted' && el.id === 'menu-nodes') {
        renderRestrictedAccess();
        return;
    }

    document.querySelectorAll('.sidebar li').forEach(li => li.classList.remove('active'));
    el.classList.add('active');

    const controls = document.getElementById('controlsContainer');
    // Nascondi controlli (namespace/refresh) se siamo sui nodi o se la risorsa è globale
    controls.style.display = (el.id === 'menu-nodes' || el.id === 'menu-storage') ? 'none' : 'flex';

    // Gestione filtri label
    const labelInput = document.getElementById('labelFilter');
    if (labelInput) {
        labelInput.style.display = (el.id === 'menu-pods' || el.id === 'menu-deps') ? 'block' : 'none';
        if (labelInput.style.display === 'none') labelInput.value = '';
    }
}

function showManualInput() {
    const container = document.getElementById('nsContextArea');
    if (!container) return;

    container.innerHTML = `
        <div class="ns-scoped-container" style="display: flex; align-items: center; gap: 10px; background: rgba(255,255,255,0.03); padding: 4px 8px; border-radius: 10px; border: 1px solid var(--border);">
            
            <div style="display: flex; align-items: center; gap: 6px; color: var(--text-muted); font-size: 0.8rem; padding-left: 4px;">
                <i class="fas fa-key" style="color: #b59a00; font-size: 0.75rem;"></i>
                <span style="font-weight: 500; font-size: 0.75rem; letter-spacing: 0.02em;">Scope:</span>
            </div>

            <input type="text" id="manualNS" value="${window.currentNamespace || ''}" 
                placeholder="Enter authorized namespace..." 
                style="width: 190px; padding: 6px 10px; border-radius: 6px; border: 1px solid var(--border); background: var(--bg-input, #fff); font-size: 0.82rem; font-family: monospace; outline: none; box-sizing: border-box;"
                onkeydown="if(event.key === 'Enter') updateNamespaceContext(this.value)">
            
            <button onclick="updateNamespaceContext(document.getElementById('manualNS').value)" 
                class="btn-small" 
                style="background: var(--accent); color: white; border: none; padding: 6px 12px; border-radius: 6px; font-size: 0.8rem; font-weight: 600; cursor: pointer; transition: opacity 0.2s;"
                onmouseover="this.style.opacity=0.9"
                onmouseout="this.style.opacity=1">
                Apply
            </button>
        </div>
    `;
}

function updateNamespaceContext(val) {
    window.currentNamespace = val;
    localStorage.setItem('last_ns', val);
    refreshCurrentView();
}


/**
 * Sostituisce il vecchio alert() con una notifica Toast non bloccante.
 * @param {string|Error} message - Il messaggio o l'oggetto errore
 * @param {string} type - 'error', 'success', 'warning' (default: error)
 */
function showError(message, type = 'error') {
    // 1. Assicuriamoci che esista il container
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        document.body.appendChild(container);
    }

    // 2. Creiamo il toast
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    // Icona in base al tipo
    const icon = type === 'success' ? 'fa-check-circle' : 'fa-exclamation-circle';
    const title = type === 'success' ? 'Success' : 'Error Detected';
    
    // Gestione del messaggio (se è un oggetto Error prendiamo .message)
    const displayMsg = message instanceof Error ? message.message : message;

    toast.innerHTML = `
        <i class="fas ${icon}"></i>
        <div class="toast-content">
            <span class="toast-title">${title}</span>
            <span class="toast-message">${displayMsg}</span>
        </div>
    `;

    // 3. Click per chiudere subito
    toast.onclick = () => removeToast(toast);

    // 4. Aggiungiamo al container
    container.appendChild(toast);

    // 5. Auto-rimozione dopo 5 secondi
    setTimeout(() => removeToast(toast), 5000);
}

function removeToast(toast) {
    toast.style.animation = 'toastFadeOut 0.3s ease-in forwards';
    toast.addEventListener('animationend', () => toast.remove());
}

// Shortcut per messaggi di successo (opzionale)
function showSuccess(msg) {
    showError(msg, 'success');
}

/**
 * Sostituisce il confirm() nativo.
 * Ritorna una Promise che risolve a true (Sì) o false (No).
 */
function showConfirm(title, message, isDanger = false) {
    return new Promise((resolve) => {
        // Creiamo o recuperiamo l'overlay
        let overlay = document.getElementById('modal-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'modal-overlay';
            document.body.appendChild(overlay);
        }

        overlay.style.display = 'flex';

        overlay.innerHTML = `
            <div class="confirm-modal">
                <h3><i class="fas ${isDanger ? 'fa-exclamation-triangle' : 'fa-question-circle'}" 
                       style="color:${isDanger ? 'var(--danger)' : 'var(--accent)'}"></i> 
                    ${title}
                </h3>
                <p>${message}</p>
                <div class="modal-footer">
                    <button class="btn-modal-cancel" id="confirm-no">Cancel</button>
                    <button class="${isDanger ? 'btn-modal-danger' : 'btn-modal-primary'}" id="confirm-yes" style="padding: 8px 20px;">
                        Confirm
                    </button>
                </div>
            </div>
        `;

        // Gestione pulsanti
        document.getElementById('confirm-yes').onclick = () => {
            overlay.style.display = 'none';
            resolve(true);
        };
        document.getElementById('confirm-no').onclick = () => {
            overlay.style.display = 'none';
            resolve(false);
        };
    });
}

/**
 * Sostituisce il prompt() nativo.
 * Ritorna una Promise che risolve alla stringa inserita o null se annullato.
 */
function showPrompt(title, message, defaultValue = '') {
    return new Promise((resolve) => {
        let overlay = document.getElementById('modal-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'modal-overlay';
            document.body.appendChild(overlay);
        }

        overlay.style.display = 'flex';

        overlay.innerHTML = `
            <div class="confirm-modal">
                <h3><i class="fas fa-edit" style="color:var(--accent)"></i> ${title}</h3>
                <p>${message}</p>
                <div class="form-group" style="margin-bottom: 1.5rem;">
                    <input type="text" id="prompt-input" value="${defaultValue}" 
                           style="width: 100%; padding: 10px; border-radius: 8px; border: 1px solid var(--border); font-family:inherit;">
                </div>
                <div class="modal-footer">
                    <button class="btn-modal-cancel" id="prompt-cancel">Cancel</button>
                    <button class="btn-modal-primary" id="prompt-ok" style="padding: 8px 20px;">Ok</button>
                </div>
            </div>
        `;

        const input = document.getElementById('prompt-input');
        input.focus();
        // Permette di premere invio invece di cliccare Save
        input.onkeydown = (e) => { if (e.key === 'Enter') document.getElementById('prompt-ok').click(); };

        document.getElementById('prompt-ok').onclick = () => {
            const val = input.value;
            overlay.style.display = 'none';
            resolve(val);
        };
        document.getElementById('prompt-cancel').onclick = () => {
            overlay.style.display = 'none';
            resolve(null);
        };
    });
}

function renderLabels(labelsObj) {
const systemLabels = ['pod-template-hash', 'controller-revision-hash', 'statefulset.kubernetes.io/pod-name'];
if (!labelsObj || Object.keys(labelsObj).length === 0) return '<span style="color:var(--text-muted)">-</span>';

const labelsHtml = Object.entries(labelsObj)
    .filter(([key]) => !systemLabels.includes(key))
    .map(([k, v]) => `<span class="label-badge" title="${k}=${v}">${k}=${v}</span>`)
    .join('');

return `<div class="labels-column">${labelsHtml || '<span style="color:var(--text-muted)">-</span>'}</div>`;
}

function showApplyForm() {
    currentView = 'upload';
    const resArea = document.getElementById('resultArea');
    document.getElementById('controlsContainer').style.display = 'none';
    resArea.innerHTML = `
        <div class="deploy-container">
            <h2>Cluster Apply</h2>
            <div class="info-note" style="background: rgba(var(--accent-rgb), 0.1); border-left: 4px solid var(--accent); padding: 12px; border-radius: 4px; margin-bottom: 20px; font-size: 0.9em; line-height: 1.4;">
                <i class="fas fa-info-circle" style="color: var(--accent); margin-right: 8px;"></i>
                <span style="color: var(--text-secondary)">
                    <strong>Note:</strong> Resources are applied based on the <code>metadata.namespace</code> defined in your manifest. 
                    Resources without a defined namespace will be directed to <strong>default</strong>. Supports multi-resource manifests. Separate distinct resources using the --- delimiter.
                </span>
            </div>
            <div class="upload-zone" style="border: 2px dashed var(--border); padding: 20px; border-radius: 12px; text-align: center; margin-bottom: 20px;">
                <label style="cursor: pointer; display: block;">
                    <i class="fas fa-cloud-upload-alt fa-2x" style="color: var(--accent)"></i><br>
                    Upload YAML file
                    <input type="file" id="fileInput" accept=".yaml,.yml" style="display:none" onchange="handleFileUpload(event)">
                </label>
                <div id="fileNameDisplay" style="margin-top:10px; font-size:0.7rem; color:var(--text-muted)">No file selected</div>
            </div>
            <textarea id="yamlEditor" style="width:100%; height:250px; border-radius:10px; border:1px solid var(--border); padding:10px;" placeholder="apiVersion: apps/v1&#10;kind: Deployment&#10;metadata:&#10;  name: my-app&#10;spec:&#10;  replicas: 2&#10;  ..."></textarea>
            <button onclick="executeApply()" class="btn-action" style="width:100%; margin-top:15px;">Run Apply</button>
            <div id="applyReport" style="margin-top:20px;"></div>
        </div>`;
}

function renderLabelFilter(visible = false) {
    const area = document.getElementById('dynamicControlsArea');
    if (!area) return;

    if (!visible) {
        area.innerHTML = '';
        return;
    }

    // Rimuoviamo il controllo "if exists return" e forziamo la pulizia
    // ma salviamo il valore se l'utente stava scrivendo
    const existingInput = document.getElementById('labelFilter');
    const savedValue = existingInput ? existingInput.value : '';

    // Ricostruiamo sempre l'area per assicurarci che sia "fresca"
    area.innerHTML = `
        <div style="position: relative; display: flex; align-items: center; gap: 5px;">
            <i class="fas fa-info-circle" style="color: var(--accent); cursor: help;" onclick="document.getElementById('filterHelp').classList.toggle('show')"></i>
            <div id="filterHelp" class="info-tooltip">
                <strong>K8s Label Selectors:</strong>
                <ul>
                    <li><code>app=web</code> : Exact match</li>
                    <li><code>app=web,env=prod</code> : Multiple (AND)</li>
                    <li><code>app!=web</code> : Exclusion</li>
                </ul>
            </div>
            <input type="text" id="labelFilter" placeholder="Filter by label..." 
                style="width: 190px; padding: 6px 10px; border-radius: 6px; border: 1px solid var(--border); background: var(--bg-input, #fff); font-size: 0.82rem; font-family: monospace; outline: none; box-sizing: border-box;"
                onkeydown="if(event.key==='Enter') refreshCurrentView()">
        </div>
    `;

    // Ripristiniamo il valore se c'era
    if (savedValue) {
        document.getElementById('labelFilter').value = savedValue;
    }
}

// --- FUNZIONE PER AGGIORNARE IL PALLINO DEGLI EVENTI ---
function updateEventsBadge(count) {
    const badge = document.getElementById('events-badge');
    if (badge) {
        if (count > 0) {
            badge.innerText = count;
            badge.style.display = 'inline-block';
        } else {
            badge.style.display = 'none';
        }
    }
}

// --- WORKER IN BACKGROUND PER GLI EVENTI (VERSIONE INTELLIGENTE) ---
async function pollEventsSilently() {
    try {
        const ns = window.currentNamespace;
        if (!ns || ns === 'undefined') return;

        const data = await apiCall(`/namespaces/${ns}/events`);
        
        if (!data || data.length === 0) {
            updateEventsBadge(0);
            return;
        }

        // 1. Tagliamo gli eventi troppo vecchi (analizziamo solo i 20 più recenti)
        const recentEvents = data.slice(0, 20);

        // 2. Mappa per registrare SOLO L'ULTIMO STATO noto di ogni singola risorsa
        const objectStatus = new Map();

        recentEvents.forEach(e => {
            const objectName = e.object || 'Unknown';
            
            // Poiché l'array è ordinato dal più nuovo al più vecchio, entriamo
            // in questo 'if' SOLO per il primo evento (il più recente) di quella risorsa.
            if (!objectStatus.has(objectName)) {
                
                const reason = (e.reason || "").toLowerCase();
                
                // NOTA: Sfruttiamo 'e.type === "Warning"' che è nativo di K8s, 
                // più i nostri filtri testuali per sicurezza
                const isWarning = e.type === 'Warning' || 
                                  reason.includes('fail') || 
                                  reason.includes('kill') || 
                                  reason.includes('backoff') ||
                                  reason.includes('unhealthy') ||
                                  reason.includes('error') ||
                                  reason.includes('evicted');
                
                // Salviamo lo stato attuale della risorsa (true = in allarme, false = ok)
                objectStatus.set(objectName, isWarning);
            }
        });

        // 3. Contiamo solo quante risorse si trovano ATTUALMENTE in stato di allarme
        let activeWarnings = 0;
        objectStatus.forEach((isWarning, objName) => {
            if (isWarning) activeWarnings++;
        });

        // Aggiorna la UI
        updateEventsBadge(activeWarnings);

    } catch (err) {
        console.warn("Background events polling failed. Retrying later.");
    }
}
