import os
import tempfile
from kubernetes import client

class K8sClientFactory:
    @staticmethod
    def get_apis(cluster_host: str, k8s_token: str, ca_cert: str = None, cluster_id: str = None):
        configuration = client.Configuration()
        configuration.host = cluster_host
        configuration.api_key['authorization'] = f"Bearer {k8s_token}"
        
        if ca_cert and "-----BEGIN CERTIFICATE-----" in ca_cert:
            # Creiamo il file temporaneo
            fd, path = tempfile.mkstemp(suffix=".crt")
            try:
                with os.fdopen(fd, 'w') as tmp:
                    tmp.write(ca_cert)
                
                configuration.verify_ssl = True
                configuration.ssl_ca_cert = path
                print(f"DEBUG: SSL configurato correttamente per {cluster_id}")
            except Exception as e:
                print(f"ERROR SSL: {e}")
                configuration.verify_ssl = False
        else:
            configuration.verify_ssl = False
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
        api_client = client.ApiClient(configuration)
        return {
            "core_v1": client.CoreV1Api(api_client),
            "apps_v1": client.AppsV1Api(api_client),
            "rbac_v1": client.RbacAuthorizationV1Api(api_client)
        }