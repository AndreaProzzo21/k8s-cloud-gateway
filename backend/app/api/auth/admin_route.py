from fastapi import APIRouter, HTTPException, Header, Depends, UploadFile, File, Form
from app.infrastructure.database import SessionLocal, ClusterModel, ProfileModel
from app.api.schemas.cluster_schema import ProfileCreate
from typing import Optional
import os

admin_router = APIRouter()
ADMIN_KEY = os.getenv("ADMIN_MASTER_KEY", "super-secret-admin-key")

def verify_admin(master_key: str = Header(...)):
    if master_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid Admin Key")

# --- CLUSTER ENDPOINT (Versione con Upload File) ---
@admin_router.post("/clusters", dependencies=[Depends(verify_admin)])
async def add_cluster(
    id: str = Form(...),
    name: str = Form(...),
    host: str = Form(...),
    ca_file: UploadFile = File(None)
):
    db = SessionLocal()
    try:
        ca_content = None
        if ca_file:
            # Leggiamo i byte grezzi dal file caricato
            file_bytes = await ca_file.read()
            # Decodifichiamo in stringa rimuovendo spazi/a capo superflui ai bordi
            ca_content = file_bytes.decode("utf-8").strip()
            
            # Controllo di integrità minimo
            if "-----BEGIN CERTIFICATE-----" not in ca_content:
                raise HTTPException(status_code=400, detail="Il file caricato non sembra un certificato PEM valido")

        new_cluster = ClusterModel(
            id=id.upper(),
            name=name,
            host=host,
            ca_cert=ca_content
        )
        
        db.merge(new_cluster)
        db.commit()
        return {"message": f"Cluster {id} registered successfully"}
    
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Il file certificato deve essere un file di testo (UTF-8)")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Errore interno: {str(e)}")
    finally:
        db.close()

# --- PROFILE ENDPOINT (Invariato, usa JSON) ---
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

# --- DELETE ENDPOINTS (Invariati) ---
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