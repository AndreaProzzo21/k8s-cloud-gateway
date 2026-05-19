# Kubernetes Multi-Cluster RBAC Gateway

> A lightweight, self-hosted control plane to manage fleet-wide Kubernetes clusters without distributing sensitive credentials.

## What it does

This platform acts as a secure proxy between your team and your Kubernetes fleet. Instead of sharing `kubeconfig` files or Service Account tokens, you register clusters once and manage access through granular profiles.

### Key Benefits:

* **Zero-Trust Delivery**: No Kubernetes credentials (`ca_cert`, `tokens`) ever reach the browser. All communication is handled server-side.
* **Unified Interface**: Access **K8s Resources**, **Helm Charts**, and **Fleet Health** from a single, elegant web dashboard.
* **Profile-Based Access**: Create multiple profiles (e.g., `admin`, `dev`, `readonly`) for the same cluster, each mapped to a specific K8s Service Account.
* **Audit-Ready**: Centralized Admin Console to monitor connectivity and compliance across all registered clusters.

---

## Deployment Options

We recommend **Docker Compose** for a standalone "Management Server" setup. Use the **Kubernetes Manifest** if you prefer hosting the gateway within an existing management cluster.

|  | Docker Compose (Recommended) | Kubernetes |
| --- | --- | --- |
| **Setup Time** | ~1 minute | ~5 minutes |
| **Persistence** | Local Folder (`./data`) | PersistentVolumeClaim |
| **Isolation** | Independent of managed clusters | Runs as a workload |

---

## 🚀 Quick Start (Docker Compose)

The fastest way to get your gateway running as a standalone control plane.

**1. Prepare the environment**
Download the `docker-compose.yml` and `.env.example` from this release, then:

```bash
mkdir k8s-gateway && cd k8s-gateway
cp .env.example .env

```

**2. Configure Secrets**
The gateway is "Smart-by-Default". If you leave `JWT_SECRET_KEY` and `ENCRYPTION_KEY` empty, the system will generate them automatically on the first boot and store them in the `data/` folder.

You **must** set the `ADMIN_MASTER_KEY` to access the Admin Console:

```dotenv
# .env
ADMIN_MASTER_KEY=your_super_secret_admin_key

```

**3. Fire it up**

```bash
docker compose up -d

```

*Log in to `http://localhost/admin.html` first to register your first cluster.*
Access the dashboard at `http://localhost`.

---

## ☸️ Kubernetes Deployment

Use the `k8s-gateway.yaml` manifest for a cloud-native deployment. It includes Nginx (Frontend) and FastAPI (Backend) with pre-configured probes and resource limits.

### Step 1: Create the Secret

Generate your keys and create the secret in the `k8s-gateway` namespace:

```bash
kubectl create namespace k8s-gateway

kubectl create secret generic gateway-secret \
  --namespace k8s-gateway \
  --from-literal=JWT_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))") \
  --from-literal=ADMIN_MASTER_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))") \
  --from-literal=ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

```

### Step 2: Storage & Apply

The manifest uses the **Default StorageClass**. Ensure one is available or edit the PVCs in the file.

```bash
kubectl apply -f k8s-gateway.yaml

```

---

## Requirements

Before deploying, ensure you have:

* **Deployment Host**: A machine with **Docker & Docker Compose** (recommended) or a **Kubernetes Cluster** where the Gateway will reside.
* **Network Visibility**: The host where the Gateway is installed must be able to reach each managed cluster's API Server (typically on port `6443`).
* **Cluster Credentials**: For each cluster you wish to manage, you need:
* The **CA Certificate** (`ca.crt`) of the cluster.
* A **Service Account (SA) Token** with the desired permissions.

---

## First Use & Architecture

The Gateway acts as an intelligent proxy. It doesn't have its own permission system; instead, it adopts the identity of the Service Account token associated with the profile you use to log in.

### 1. The "Power User" Profile (Required for Audit & Monitoring)

To take full advantage of the **Fleet Observation** and **Built-in Audit Engine**, you must register at least one high-privilege profile for each cluster.

* **Permissions**: This profile should be backed by an SA with `cluster-admin` or broad read-overseer powers.
* **Naming Convention**: On the Gateway Admin Console, this profile **MUST** be named exactly **`admin`**, **`cluster-admin`**, or **`gateway-admin`**.
* **Why?**: The background Audit & Observer engine specifically looks for these profile names to scan clusters, run compliance rules, and provide the global health overview. You can toggle specific audit rules on or off directly from the Admin Console.

### 2. Team Profiles (RBAC Delegation)

Once the admin profile is set, create as many profiles as you need for your team.

* **RBAC Mirroring**: If you link a profile to an SA that only has `read` access to the `staging` namespace, the Gateway UI will automatically restrict that user, hiding other namespaces and disabling delete/scale actions.
* **Safety**: This allows you to give developers access to specific workloads without ever handing them a `kubeconfig` or a direct token.

---

## Setup Workflow

### Step 1: Prepare the Target Cluster

Run these commands on the cluster you want to manage to create a dedicated admin SA:

```bash
# Create SA and bind to cluster-admin
kubectl create serviceaccount gateway-admin -n kube-system
kubectl create clusterrolebinding gateway-admin-binding --clusterrole=cluster-admin --serviceaccount=kube-system:gateway-admin

# Generate a long-lived token
kubectl create token gateway-admin -n kube-system --duration=8760h

```

### Step 2: Register via Admin Console

1. Navigate to `<GATEWAY_URL>/admin.html` and log in with your `ADMIN_MASTER_KEY`.
2. **Add Cluster**: Upload the `ca.crt` and set the API Server URL.
3. **Add Profile**: Create the `admin` profile using the token from Step 1.
4. **Verify**: Check the **Fleet Health** tab; the cluster should now appear with its live status and node/pod counts.

---

## Dashboard Overview

### 📦 K8s Console

Full visibility into workloads (Pods, Deployments), Networking (Services, Ingress), and Storage. Includes a built-in YAML editor to apply manifests directly.

### ☸️ Helm Console

Manage releases without the Helm CLI. Install from private and public repositories or upload ZIPs. Supports linting, history inspection, and one-click rollbacks.

### 🛡️ Admin Console

The "Brain" of the gateway.

* **Fleet Health**: Real-time status of all registered clusters.
* **Profile Management**: Map different team roles to different K8s permissions.
* **Audit**: Verify which clusters are reachable and compliant.

---

## Security Design

* **HttpOnly Cookies**: JWTs are stored in browser cookies that are inaccessible to JavaScript, mitigating XSS risks.
* **Encryption-at-Rest**: Sensitive K8s tokens are encrypted in the SQLite database using Fernet (AES-128).
* **No Agent Required**: The gateway uses standard K8s API calls. No custom controllers or agents need to be installed on your managed clusters.

---

### 📖 Full Documentation

For API specs, internal request lifecycles, and advanced configuration, visit:
**[github.com/AndreaProzzo21/k8s-cloud-gateway](https://github.com/AndreaProzzo21/k8s-cloud-gateway)**

---

