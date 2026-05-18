from fastapi import APIRouter, HTTPException, Header, Depends, UploadFile, File, Form, Body
from app.infrastructure.database import SessionLocal, ClusterModel, ProfileModel
from app.api.schemas.cluster_schema import ProfileCreate
from app.api.dependencies.get_admin_key import require_admin_key
from app.core.fleet_manager import FleetManager
from app.infrastructure.cluster_scanner import scan_all_clusters
from typing import Optional
import os

admin_router = APIRouter()

# --- CLUSTER ENDPOINT (Versione con Upload File) ---
@admin_router.post("/clusters", dependencies=[Depends(require_admin_key)])
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
@admin_router.post("/profiles", dependencies=[Depends(require_admin_key)])
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
@admin_router.delete("/clusters/{cluster_id}", dependencies=[Depends(require_admin_key)])
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

@admin_router.delete("/profiles/{profile_id}", dependencies=[Depends(require_admin_key)])
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

# --- GET ENDPOINTS (Retrieve) ---

# --- GET ENDPOINTS con supporto Query ---

@admin_router.get("/clusters", dependencies=[Depends(require_admin_key)])
async def list_clusters(search: Optional[str] = None):
    db = SessionLocal()
    try:
        query = db.query(ClusterModel)
        if search:
            # Filtra per ID o per Nome (case-insensitive)
            query = query.filter(
                (ClusterModel.id.ilike(f"%{search}%")) | 
                (ClusterModel.name.ilike(f"%{search}%"))
            )
        clusters = query.all()
        return [{
            "id": c.id, 
            "name": c.name, 
            "host": c.host, 
            "has_ca": bool(c.ca_cert)
        } for c in clusters]
    finally:
        db.close()

@admin_router.get("/profiles", dependencies=[Depends(require_admin_key)])
async def list_profiles(cluster_id: Optional[str] = None, name: Optional[str] = None):
    db = SessionLocal()
    try:
        query = db.query(ProfileModel)
        if cluster_id:
            query = query.filter(ProfileModel.cluster_id == cluster_id.upper())
        if name:
            query = query.filter(ProfileModel.name.ilike(f"%{name}%"))
            
        profiles = query.all()
        return [{
            "id": p.id,
            "cluster_id": p.cluster_id,
            "name": p.name,
            "has_token": bool(p.k8s_token)
        } for p in profiles]
    finally:
        db.close()

# --- PATCH ENDPOINTS (Update) ---

@admin_router.patch("/clusters/{cluster_id}", dependencies=[Depends(require_admin_key)])
async def update_cluster(
    cluster_id: str, 
    name: Optional[str] = Form(None),
    host: Optional[str] = Form(None),
    ca_file: Optional[UploadFile] = File(None)
):
    db = SessionLocal()
    try:
        cluster = db.query(ClusterModel).filter(ClusterModel.id == cluster_id.upper()).first()
        if not cluster:
            raise HTTPException(status_code=404, detail="Cluster not found")

        if name: cluster.name = name
        if host: cluster.host = host
        if ca_file:
            content = await ca_file.read()
            cluster.ca_cert = content.decode("utf-8").strip()

        db.commit()
        return {"message": f"Cluster {cluster_id} updated"}
    finally:
        db.close()

@admin_router.patch("/profiles/{profile_id}", dependencies=[Depends(require_admin_key)])
async def update_profile(
    profile_id: int, 
    name: Optional[str] = Body(None),            # <--- AGGIUNGI QUESTO
    cluster_id: Optional[str] = Body(None),      # <--- AGGIUNGI QUESTO (opzionale)
    gateway_password: Optional[str] = Body(None),
    k8s_token: Optional[str] = Body(None)
):
    db = SessionLocal()
    try:
        profile = db.query(ProfileModel).filter(ProfileModel.id == profile_id).first()
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")

        # Aggiorna i campi solo se presenti nella richiesta
        if name: profile.name = name
        if cluster_id: profile.cluster_id = cluster_id.upper()
        if gateway_password: profile.gateway_password = gateway_password
        if k8s_token: profile.k8s_token = k8s_token

        db.commit()
        return {"message": f"Profile {profile_id} updated successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@admin_router.get("/fleet/status", dependencies=[Depends(require_admin_key)])
async def get_fleet_status(refresh: bool = False):
    """
    Restituisce lo stato della flotta. 
    Se refresh=true, forza una scansione immediata (lenta),
    altrimenti restituisce la cache (istantanea).
    """
    if refresh:
        # Forza scan reale se l'admin preme un tasto "Refresh" dedicato
        return await scan_all_clusters()
    
    # Restituisce i dati pronti in memoria
    return FleetManager.get_cached_status()