from app.infrastructure.database import SessionLocal, ClusterModel, ProfileModel

class ClusterRegistry:
    @staticmethod
    def get_cluster_data(cluster_id: str, profile_name: str):
        db = SessionLocal()
        try:
            # 1. Cerchiamo il profilo. Usiamo .filter() per essere sicuri.
            # Nota: .lower() o .upper() devono combaciare con come hai salvato i dati
            profile = db.query(ProfileModel).filter(
                ProfileModel.cluster_id == cluster_id.upper(),
                ProfileModel.name == profile_name # Assicurati che qui non serva .lower()
            ).first()

            if not profile:
                print(f"DEBUG: Profile {profile_name} not found for cluster {cluster_id}")
                return None

            # 2. Grazie alla relationship "cluster" definita nel modello, 
            # SQLAlchemy recupera automaticamente il cluster associato
            cluster = profile.cluster 
            
            if not cluster:
                print(f"DEBUG: Cluster {cluster_id} linked to profile not found")
                return None

            return {
                "host": cluster.host,
                "token": profile.k8s_token,
                "gateway_password": profile.gateway_password,
                "ca_cert": cluster.ca_cert
            }
        finally:
            db.close()