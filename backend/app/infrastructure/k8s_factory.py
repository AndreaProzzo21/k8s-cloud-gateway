import os
from kubernetes import client

class K8sClientFactory:
    @staticmethod
    def get_apis(cluster_host: str, k8s_token: str):
        configuration = client.Configuration()
        configuration.host = cluster_host
        configuration.api_key['authorization'] = f"Bearer {k8s_token}"
        
        # --- CONFIGURAZIONE SSL CON CA ---
        # Recuperiamo il path del CA dalle variabili d'ambiente o usiamo un default
        ca_path = os.getenv("K8S_CA_CERT_PATH", "/app/certs/ca.crt")
        
        if os.path.exists(ca_path):
            configuration.verify_ssl = True
            configuration.ssl_ca_cert = ca_path
        else:
            # Fallback (opzionale) se il file non esiste per qualche motivo
            print(f"ATTENZIONE: CA cert non trovato in {ca_path}. Procedo senza verifica.")
            configuration.verify_ssl = False
        # ----------------------------------
        
        api_client = client.ApiClient(configuration)
        
        return {
            "core_v1": client.CoreV1Api(api_client),
            "apps_v1": client.AppsV1Api(api_client)
        }