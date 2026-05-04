from pydantic import BaseModel
from typing import Optional

class ClusterCreate(BaseModel):
    id: str  # es. "PROD"
    name: str
    host: str
    ca_cert: Optional[str] = None

class ProfileCreate(BaseModel):
    cluster_id: str
    name: str
    gateway_password: str
    k8s_token: str