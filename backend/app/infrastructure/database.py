"""
database.py
===========

Modelli SQLAlchemy e configurazione della sessione del gateway.

Cifratura dei campi sensibili
------------------------------
I campi ``gateway_password``, ``k8s_token`` e ``ca_cert`` usano
``EncryptedString``, un ``TypeDecorator`` che cifra automaticamente
i valori prima della persistenza e li decifra dopo il recupero.

Il resto del codice (registry.py, auth_handler.py, admin_routes.py)
non sa che i dati sono cifrati su disco: legge e scrive stringhe normali.

Campi cifrati
-------------
- ``ProfileModel.gateway_password``  — password di login al gateway
- ``ProfileModel.k8s_token``         — SA token Kubernetes
- ``ClusterModel.ca_cert``           — CA Certificate PEM

Campi in chiaro
---------------
- ``ClusterModel.id``, ``ClusterModel.name``, ``ClusterModel.host``
- ``ProfileModel.cluster_id``, ``ProfileModel.name``
  (usati come chiavi di lookup — devono restare leggibili)
- ``AuditRuleConfig.*`` — tutti in chiaro: non contiene credenziali,
  solo riferimenti a regole e flag booleani.

Tabelle
-------
- ``clusters``           — cluster Kubernetes registrati
- ``profiles``           — profili Service Account per cluster
- ``audit_rule_configs`` — configurazione per-cluster delle audit rules

Logica default delle regole
----------------------------
Se non esiste un record in ``audit_rule_configs`` per una coppia
(cluster_id, rule_id), la regola si considera **abilitata per default**.
Questo approccio "default-on" garantisce che un cluster appena registrato
sia sottoposto all'intera suite di audit senza configurazione manuale,
il che è il comportamento corretto per un sistema di compliance.
Un record esiste solo quando l'admin ha *modificato* il default.
"""

import os

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.infrastructure.encryption import decrypt, encrypt
from app.core.config import settings


# ---------------------------------------------------------------------------
# Connessione al database
# ---------------------------------------------------------------------------

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ---------------------------------------------------------------------------
# EncryptedString — TypeDecorator per la cifratura automatica
# ---------------------------------------------------------------------------

class EncryptedString(TypeDecorator):
    """
    Tipo SQLAlchemy che cifra i valori prima di INSERT/UPDATE
    e li decifra dopo SELECT.

    È un drop-in replacement di ``String`` / ``Text``: il codice
    che accede ai modelli riceve sempre la stringa in chiaro.

    Valori NULL
    -----------
    Se il valore è ``None``, viene passato invariato — SQLAlchemy
    gestisce NULL nativamente e non ha senso cifrare NULL.

    Migrazione da dati in chiaro
    ----------------------------
    Se nel DB esistono righe con valori non ancora cifrati, eseguire
    ``migrate_encrypt.py`` PRIMA di riavviare il gateway con questa versione.
    """

    impl     = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        """Cifra prima di scrivere sul DB (INSERT / UPDATE)."""
        if value is None:
            return None
        return encrypt(value)

    def process_result_value(self, value, dialect):
        """Decifra dopo aver letto dal DB (SELECT)."""
        if value is None:
            return None
        return decrypt(value)


# ---------------------------------------------------------------------------
# Modelli
# ---------------------------------------------------------------------------

class ClusterModel(Base):
    """
    Cluster Kubernetes registrato nel gateway.

    ``id`` è la chiave primaria scelta dall'admin (es. "TESI", "K3S").
    Deve essere univoco e stabile: viene usato come chiave JWT, come
    chiave della cert cache nella factory, e come FK in ``profiles``
    e ``audit_rule_configs``.
    """

    __tablename__ = "clusters"

    id      = Column(String,          primary_key=True)
    name    = Column(String,          nullable=False)
    host    = Column(String,          nullable=False)
    ca_cert = Column(EncryptedString, nullable=True)

    profiles     = relationship(
        "ProfileModel",
        back_populates="cluster",
        cascade="all, delete",
    )
    audit_configs = relationship(
        "AuditRuleConfig",
        back_populates="cluster",
        cascade="all, delete",
    )


class ProfileModel(Base):
    """
    Profilo Service Account associato a un cluster.

    Ogni profilo corrisponde a un Service Account K8s con determinati
    permessi RBAC. L'utente fa login con (cluster_id, profile_name, password)
    e riceve un JWT che identifica la sessione.

    I campi sensibili (``gateway_password``, ``k8s_token``) sono cifrati
    su disco tramite ``EncryptedString``.
    """

    __tablename__ = "profiles"

    id               = Column(Integer,          primary_key=True, autoincrement=True)
    cluster_id       = Column(String,           ForeignKey("clusters.id"))
    name             = Column(String,           nullable=False)
    gateway_password = Column(EncryptedString,  nullable=False)
    k8s_token        = Column(EncryptedString,  nullable=False)

    cluster = relationship("ClusterModel", back_populates="profiles")


class AuditRuleConfig(Base):
    """
    Configurazione per-cluster di una singola audit rule.

    Design
    ------
    Un record esiste solo quando l'admin ha *modificato* il default.
    Se non esiste un record per (cluster_id, rule_id), il codice
    dell'audit engine considera la regola **abilitata** (default-on).

    Questo significa:
    - Un cluster appena registrato eredita automaticamente tutte le regole
      attive senza nessuna configurazione manuale.
    - Disabilitare una regola crea (o aggiorna) un record con enabled=False.
    - Ri-abilitare una regola può sia impostare enabled=True sia eliminare
      il record — entrambi producono lo stesso comportamento.

    Campi
    -----
    cluster_id : FK verso clusters.id, cascade delete — se il cluster viene
                 eliminato, tutte le sue configurazioni vengono rimosse.
    rule_id    : stringa che identifica la regola nel codice, es.
                 "node-ready", "rbac-admin-audit", "no-failed-pods".
                 Non è una FK verso una tabella di regole perché le regole
                 sono definite nel codice (audit_engine.py), non nel DB.
    enabled    : se False, la regola non viene eseguita su questo cluster
                 anche se è definita nell'engine.
    note       : motivazione opzionale dell'admin per la disabilitazione,
                 es. "cluster di sviluppo — privilegi elevati accettati".
                 Utile per audit trail e documentazione interna.

    Vincoli
    -------
    UNIQUE (cluster_id, rule_id) garantisce un solo record per coppia.
    Il codice usa upsert (INSERT OR REPLACE in SQLite) per aggiornare
    la configurazione senza dover fare GET prima di ogni PATCH.
    """

    __tablename__ = "audit_rule_configs"

    __table_args__ = (
        UniqueConstraint("cluster_id", "rule_id", name="uq_cluster_rule"),
    )

    id         = Column(Integer, primary_key=True, autoincrement=True)
    cluster_id = Column(String,  ForeignKey("clusters.id", ondelete="CASCADE"), nullable=False)
    rule_id    = Column(String,  nullable=False)
    enabled    = Column(Boolean, nullable=False, default=True)
    note       = Column(String,  nullable=True)

    cluster = relationship("ClusterModel", back_populates="audit_configs")


# ---------------------------------------------------------------------------
# Creazione tabelle
# ---------------------------------------------------------------------------

def init_db():
    """
    Crea tutte le tabelle se non esistono.

    Chiamata all'avvio del gateway (tipicamente in main.py o nel lifespan).
    È idempotente: se le tabelle esistono già non le ricrea né le modifica.

    Nota: ``AuditRuleConfig`` viene creata automaticamente insieme alle
    altre — non serve nessuna migration manuale per i DB esistenti,
    perché SQLAlchemy usa CREATE TABLE IF NOT EXISTS.
    """
    if not os.path.exists("data"):
        os.makedirs("data")
    Base.metadata.create_all(bind=engine)