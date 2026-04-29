import os

class ClusterRegistry:
    @staticmethod
    def get_cluster_data(cluster_id: str, profile_name: str):
        """
        Recupera i dati di un profilo specifico per un cluster.
        """
        prefix = f"CLUSTER_{cluster_id.upper()}_"
        host = os.getenv(f"{prefix}HOST")
        
        if not host:
            return None

        # Carichiamo i dati specifici del profilo richiesto
        profile_suffix = profile_name.upper().replace("-", "_")
        token = os.getenv(f"{prefix}TOKEN_{profile_suffix}")
        password = os.getenv(f"{prefix}PASS_{profile_suffix}")

        if not token or not password:
            return None

        return {
            "host": host,
            "token": token,
            "gateway_password": password
        }