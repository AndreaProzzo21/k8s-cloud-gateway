const API_BASE = "/api/v1";
window.apiAbortController = new AbortController();
window._dashboardReady = false;

async function apiCall(endpoint, method = 'GET', isText = false, body = null) {
    // Niente più localStorage né header Authorization:
    // il browser allega automaticamente il cookie httpOnly k8s_jwt
    const signal = window.apiAbortController.signal;

    const options = {
        method,
        credentials: 'include',   // ← unica riga aggiunta
        headers: {
            'Connection': 'close'
        },
        signal
    };

    if (body instanceof FormData) {
        options.body = body;
    } else if (body) {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(body);
    }

    try {
        const response = await fetch(`${API_BASE}${endpoint}`, options);

        if (response.status === 401 || response.status === 403) {
            throw new Error("RESTRICTED");
        }

        if (response.status === 504 || response.status === 503) {
            if (window._dashboardReady) {
                _handleClusterUnreachable();
                return new Promise(() => {});
            } else {
                throw new Error("CLUSTER_UNREACHABLE");
            }
        }

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.message || errorData.detail || "API ERROR");
        }

        return isText ? await response.text() : await response.json();

    } catch (error) {
        if (error.name === 'AbortError') {
            console.warn("Request aborted.");
            return new Promise(() => {});
        }
        throw error;
    }
}

async function _handleClusterUnreachable() {
    sessionStorage.setItem('login_error', 'Cluster unreachable or timed out. Please check the cluster status and try again.');
    // Il backend cancella il cookie; il localStorage non esiste più
    try {
        await fetch(`${API_BASE}/auth/logout`, {
            method: 'POST',
            credentials: 'include'
        });
    } catch (_) {
        // Se il logout fallisce (backend irraggiungibile) non blocchiamo il redirect
    }
    window.location.replace('index.html');
}

function handleFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;
    document.getElementById('fileNameDisplay').innerText = `File: ${file.name}`;
    const reader = new FileReader();
    reader.onload = (e) => document.getElementById('yamlEditor').value = e.target.result;
    reader.readAsText(file);
}