from app.core.exceptions import (
    K8sResourceNotFoundException, 
    K8sUnauthorisedException, 
    K8sCommunicationException,
    K8sBaseException # Assicurati che sia importata per create_deployment
)
from kubernetes.client.rest import ApiException
import yaml
from datetime import datetime


class CoreManager:
    def __init__(self, k8s_apis: dict):
        """
        Il costruttore riceve il dizionario di API generato dalla Factory.
        Non c'è più un'istanza globale Singleton.
        """
        self.core_v1 = k8s_apis["core_v1"]
        self.apps_v1 = k8s_apis["apps_v1"]

    # --- POD OPERATIONS ---

    def get_pods_in_namespace(self, namespace: str):
        try:
            pods_data = self.core_v1.list_namespaced_pod(namespace)
            return [
                {
                    "name": pod.metadata.name,
                    "status": pod.status.phase,
                    "pod_ip": pod.status.pod_ip,
                    "creation_timestamp": pod.metadata.creation_timestamp
                }
                for pod in pods_data.items
            ]
        except ApiException as e:
            self._handle_exception(e, f"Namespace '{namespace}'")

    def get_pod_by_name(self, name: str, namespace: str):
        try:
            pod = self.core_v1.read_namespaced_pod(name=name, namespace=namespace)
            return {
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "status": pod.status.phase,
                "pod_ip": pod.status.pod_ip,
                "host_ip": pod.status.host_ip,
                "start_time": pod.status.start_time,
                "labels": pod.metadata.labels
            }
        except ApiException as e:
            self._handle_exception(e, f"Pod '{name}' nel namespace '{namespace}'")


    def get_pod_logs(self, name: str, namespace: str, tail_lines: int = None):
        """Recupera i log di un pod. Se tail_lines è definito, recupera solo le ultime N righe."""
        try:
            params = {"name": name, "namespace": namespace}
            if tail_lines:
                params["tail_lines"] = tail_lines
            
            # Ritorna il log come stringa piana
            return self.core_v1.read_namespaced_pod_log(**params)
        except ApiException as e:
            self._handle_exception(e, f"Log del Pod '{name}'")

    # --- DEPLOYMENT OPERATIONS ---

    def list_deployments_in_namespace(self, namespace: str):
        try:
            deployments = self.apps_v1.list_namespaced_deployment(namespace)
            return [
                {
                    "name": dep.metadata.name,
                    "replicas_desired": dep.spec.replicas,
                    "replicas_ready": dep.status.ready_replicas or 0,
                    "status": "Ready" if dep.spec.replicas == dep.status.ready_replicas else "Updating",
                    "creation_timestamp": dep.metadata.creation_timestamp
                }
                for dep in deployments.items
            ]
        except ApiException as e:
            self._handle_exception(e, f"Namespace '{namespace}'")

    def get_deployment_by_name(self, name: str, namespace: str):
        try:
            dep = self.apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
            return {
                "name": dep.metadata.name,
                "namespace": dep.metadata.namespace,
                "replicas_spec": dep.spec.replicas,
                "replicas_status": {
                    "total": dep.status.replicas or 0,
                    "updated": dep.status.updated_replicas or 0,
                    "available": dep.status.available_replicas or 0,
                    "ready": dep.status.ready_replicas or 0
                },
                "strategy": dep.spec.strategy.type,
                "image": dep.spec.template.spec.containers[0].image,
                "labels": dep.metadata.labels
            }
        except ApiException as e:
            self._handle_exception(e, f"Deployment '{name}' nel namespace '{namespace}'")


    def scale_deployment(self, name: str, namespace: str, replicas: int):
        """Scala il numero di repliche di un deployment."""
        try:
            body = {"spec": {"replicas": replicas}}
            return self.apps_v1.patch_namespaced_deployment_scale(
                name=name, 
                namespace=namespace, 
                body=body
            )
        except ApiException as e:
            self._handle_exception(e, f"Scaling Deployment '{name}'")

    def restart_deployment(self, name: str, namespace: str):
        """Esegue il rollout restart di un deployment (aggiornando l'annotazione del template)."""
        try:
            # Simuliamo il rollout restart aggiornando un'annotazione nel template
            now = datetime.utcnow().isoformat() + "Z"
            body = {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "kubectl.kubernetes.io/restartedAt": now
                            }
                        }
                    }
                }
            }
            return self.apps_v1.patch_namespaced_deployment(
                name=name, 
                namespace=namespace, 
                body=body
            )
        except ApiException as e:
            self._handle_exception(e, f"Restart Deployment '{name}'")

    def delete_deployment(self, name: str, namespace: str):
        """Elimina un deployment specifico."""
        try:
            return self.apps_v1.delete_namespaced_deployment(
                name=name,
                namespace=namespace
            )
        except ApiException as e:
            self._handle_exception(e, f"Eliminazione Deployment '{name}'")


    # --- SERVICE OPERATIONS ---

    def list_services_in_namespace(self, namespace: str):
        try:
            services = self.core_v1.list_namespaced_service(namespace)
            return [
                {
                    "name": svc.metadata.name,
                    "type": svc.spec.type,
                    "cluster_ip": svc.spec.cluster_ip,
                    "ports": [
                        {"port": p.port, "protocol": p.protocol, "target_port": p.target_port} 
                        for p in svc.spec.ports
                    ] if svc.spec.ports else [],
                    "creation_timestamp": svc.metadata.creation_timestamp
                }
                for svc in services.items
            ]
        except ApiException as e:
            self._handle_exception(e, f"Namespace '{namespace}'")

    def get_service_by_name(self, name: str, namespace: str):
        try:
            svc = self.core_v1.read_namespaced_service(name=name, namespace=namespace)
            return {
                "name": svc.metadata.name,
                "namespace": svc.metadata.namespace,
                "type": svc.spec.type,
                "cluster_ip": svc.spec.cluster_ip,
                "external_ip": svc.status.load_balancer.ingress[0].ip if svc.status.load_balancer.ingress else None,
                "selector": svc.spec.selector,
                "ports": [
                    {"name": p.name, "port": p.port, "protocol": p.protocol, "target_port": p.target_port} 
                    for p in svc.spec.ports
                ] if svc.spec.ports else []
            }
        except ApiException as e:
            self._handle_exception(e, f"Service '{name}' nel namespace '{namespace}'")

    # --- WRITE OPERATIONS ---

    def create_deployment(self, namespace: str, yaml_content: str):
        try:
            dep_dict = yaml.safe_load(yaml_content)
            if dep_dict.get("kind") != "Deployment":
                raise K8sBaseException("Il file caricato non è un Deployment", status_code=400)

            response = self.apps_v1.create_namespaced_deployment(
                namespace=namespace,
                body=dep_dict
            )
            return {
                "status": "success",
                "name": response.metadata.name,
                "message": f"Risorsa {response.metadata.name} deployata con successo"
            }
        except yaml.YAMLError:
            raise K8sBaseException("Sintassi YAML non valida", status_code=400)
        except ApiException as e:
            if e.status == 409:
                raise K8sBaseException("La risorsa esiste già", status_code=409)
            self._handle_exception(e, "Operazione di Deploy")

    # --- HELPER PER ECCEZIONI ---

    def _handle_exception(self, e: ApiException, context: str):
        """Metodo interno per centralizzare la gestione degli errori API."""
        if e.status == 404:
            raise K8sResourceNotFoundException(f"{context} non trovato", status_code=404)
        elif e.status in [401, 403]:
            raise K8sUnauthorisedException(f"Permessi insufficienti per {context}", status_code=e.status)
        else:
            raise K8sCommunicationException(f"Errore API Kubernetes ({context}): {e.reason}", status_code=e.status)