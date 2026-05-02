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
        
        # Cerchiamo un file che si chiama come l'ID (es. LAB.crt, PROD.crt)
        specific_ca = f"/app/certs/{cluster_id}.crt" if cluster_id else None
        

        # Logica di selezione del Certificato
        if specific_ca and os.path.exists(specific_ca):
            # Se esiste il certificato specifico per quel cluster ID
            configuration.verify_ssl = True
            configuration.ssl_ca_cert = specific_ca
        else:
            configuration.verify_ssl = False
            configuration.ssl_ca_cert = False
            print(f"DEBUG: No CA found for {cluster_id}. SSL Verification disabled.")

        api_client = client.ApiClient(configuration)
        
        return {
            "core_v1": client.CoreV1Api(api_client),
            "apps_v1": client.AppsV1Api(api_client),
            "rbac_v1": client.RbacAuthorizationV1Api(api_client)
        }