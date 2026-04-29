import os
from kubernetes import client

class K8sClientFactory:
    @staticmethod
    def get_apis(cluster_host: str, k8s_token: str, cluster_id: str = None):
        """
        Inizializza i client K8s. 
        Se cluster_id è fornito, cerca un certificato specifico.
        """
        configuration = client.Configuration()
        configuration.host = cluster_host
        configuration.api_key['authorization'] = f"Bearer {k8s_token}"
        
        # 1. Definizione dei percorsi
        # Cerchiamo un file che si chiama come l'ID (es. LAB.crt, PROD.crt)
        specific_ca = f"/app/certs/{cluster_id}.crt" if cluster_id else None
        default_ca = os.getenv("K8S_CA_CERT_PATH", "/app/certs/ca.crt")

        # 2. Logica di selezione del Certificato
        if specific_ca and os.path.exists(specific_ca):
            # Se esiste il certificato specifico per quel cluster ID
            configuration.verify_ssl = True
            configuration.ssl_ca_cert = specific_ca
        elif os.path.exists(default_ca):
            # Se non c'è quello specifico, proviamo quello di default
            configuration.verify_ssl = True
            configuration.ssl_ca_cert = default_ca
        else:
            # Se non troviamo nulla, andiamo in modalità insicura (per test/minikube)
            configuration.verify_ssl = False
            configuration.assert_hostname = False
            # Opzionale: stampa un warning nei log del container
            print(f"DEBUG: No CA found for {cluster_id}. SSL Verification disabled.")

        api_client = client.ApiClient(configuration)
        
        return {
            "core_v1": client.CoreV1Api(api_client),
            "apps_v1": client.AppsV1Api(api_client)
        }