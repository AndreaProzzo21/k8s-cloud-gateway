from fastapi import APIRouter, HTTPException, Header, Depends
from app.infrastructure.database import SessionLocal, ClusterModel, ProfileModel
from app.api.schemas.cluster_schema import ClusterCreate, ProfileCreate
import os

admin_router = APIRouter()
ADMIN_KEY = os.getenv("ADMIN_MASTER_KEY", "super-secret-admin-key")

def verify_admin(master_key: str = Header(...)):
    if master_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid Admin Key")

@admin_router.post("/clusters", dependencies=[Depends(verify_admin)])
async def add_cluster(cluster_data: ClusterCreate):
    db = SessionLocal()
    try:
        new_cluster = ClusterModel(
            id=cluster_data.id.upper(),
            name=cluster_data.name,
            host=cluster_data.host,
            ca_cert=cluster_data.ca_cert
        )
        db.merge(new_cluster) # merge aggiorna se esiste, crea se manca
        db.commit()
        return {"message": f"Cluster {cluster_data.id} registered"}
    finally:
        db.close()

@admin_router.post("/profiles", dependencies=[Depends(verify_admin)])
async def add_profile(profile_data: ProfileCreate):
    db = SessionLocal()
    try:
        new_profile = ProfileModel(
            cluster_id=profile_data.cluster_id.upper(),
            name=profile_data.name,
            gateway_password=profile_data.gateway_password,
            k8s_token=profile_data.k8s_token
        )
        db.add(new_profile)
        db.commit()
        return {"message": f"Profile {profile_data.name} added to cluster {profile_data.cluster_id}"}
    finally:
        db.close()

@admin_router.delete("/clusters/{cluster_id}", dependencies=[Depends(verify_admin)])
async def delete_cluster(cluster_id: str):
    db = SessionLocal()
    try:
        cluster = db.query(ClusterModel).filter(ClusterModel.id == cluster_id.upper()).first()
        if not cluster:
            raise HTTPException(status_code=404, detail="Cluster not found")
        
        db.delete(cluster)
        db.commit()
        return {"message": f"Cluster {cluster_id} and all associated profiles deleted"}
    finally:
        db.close()

@admin_router.delete("/profiles/{profile_id}", dependencies=[Depends(verify_admin)])
async def delete_profile(profile_id: int):
    db = SessionLocal()
    try:
        profile = db.query(ProfileModel).filter(ProfileModel.id == profile_id).first()
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        
        db.delete(profile)
        db.commit()
        return {"message": f"Profile {profile_id} deleted"}
    finally:
        db.close()