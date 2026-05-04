from sqlalchemy import create_engine, Column, String, Integer, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import os

# Folder 'data' in root
DB_PATH = "data/gateway.db"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class ClusterModel(Base):
    __tablename__ = "clusters"
    id = Column(String, primary_key=True) # es. "TESI"
    name = Column(String, nullable=False)
    host = Column(String, nullable=False) # url api server
    ca_cert = Column(Text, nullable=True) # Possiamo salvare il cert direttamente qui o il path

    profiles = relationship("ProfileModel", back_populates="cluster", cascade="all, delete")

class ProfileModel(Base):
    __tablename__ = "profiles"
    id = Column(Integer, primary_key=True, autoincrement=True)
    cluster_id = Column(String, ForeignKey("clusters.id"))
    name = Column(String, nullable=False) # es. "admin", "dev"
    gateway_password = Column(String, nullable=False) # Password per il login al gateway
    k8s_token = Column(Text, nullable=False) # Il token del Service Account

    cluster = relationship("ClusterModel", back_populates="profiles")

# Creazione tabelle
def init_db():
    if not os.path.exists("data"):
        os.makedirs("data")
    Base.metadata.create_all(bind=engine)