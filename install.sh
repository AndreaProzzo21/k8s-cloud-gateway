#!/usr/bin/env bash

# ==============================================================================
# KUBERNETES MULTI-CLUSTER RBAC GATEWAY - BOOTSTRAP SCRIPT
# ==============================================================================
# Strict mode: fail on any error, unset variable, or pipe failure
set -euo pipefail

# --- UI Helpers ---
C_RESET='\033[0m'
C_BLUE='\033[1;34m'
C_GREEN='\033[1;32m'
C_YELLOW='\033[1;33m'
C_RED='\033[1;31m'
C_CYAN='\033[1;36m'

print_step() { echo -e "\n${C_BLUE}==>${C_RESET} ${C_CYAN}$1${C_RESET}"; }
print_info() { echo -e "    $1"; }
print_warn() { echo -e "    ${C_YELLOW}WARNING:${C_RESET} $1"; }
print_err()  { echo -e "    ${C_RED}ERROR:${C_RESET} $1"; }
print_success() { echo -e "    ${C_GREEN}✔${C_RESET} $1"; }

# --- Configuration ---
# CHANGE THIS TO YOUR ACTUAL GITHUB RAW URL
REPO_URL="https://raw.githubusercontent.com/AndreaProzzo21/k8s-cloud-gateway/main"
COMPOSE_FILE_URL="${REPO_URL}/docker-compose-deploy/docker-compose.yml"
ENV_EXAMPLE_URL="${REPO_URL}/docker-compose-deploy/.env.example"
README_URL="${REPO_URL}/deploy/deploy-docker-compose/README.md"
INSTALL_DIR="k8s-gateway"

clear
echo -e "${C_BLUE}"
echo "██╗  ██╗██████╗ ███████╗     ██████╗  █████╗ ████████╗███████╗██╗    ██╗ █████╗ ██╗   ██╗"
echo "██║ ██╔╝██╔══██╗██╔════╝    ██╔════╝ ██╔══██╗╚══██╔══╝██╔════╝██║    ██║██╔══██╗╚██╗ ██╔╝"
echo "█████╔╝  █████╔╝███████╗    ██║  ███╗███████║   ██║   █████╗  ██║ █╗ ██║███████║ ╚████╔╝ "
echo "██╔═██╗ ██╔══██╗╚════██║    ██║   ██║██╔══██║   ██║   ██╔══╝  ██║███╗██║██╔══██║  ╚██╔╝  "
echo "██║  ██╗██████╔╝███████║    ╚██████╔╝██║  ██║   ██║   ███████╗╚███╔███╔╝██║  ██║   ██║   "
echo "╚═╝  ╚═╝╚═════╝ ╚══════╝     ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚══════╝ ╚══╝╚══╝ ╚═╝  ╚═╝   ╚═╝   "
echo -e "${C_RESET}"
echo -e "Welcome to the interactive installer. This script will set up your control plane.\n"

# ==============================================================================
# 1. PRE-FLIGHT CHECKS
# ==============================================================================
print_step "Running pre-flight checks..."

if ! command -v curl >/dev/null 2>&1; then
    print_err "curl is required but not installed. Aborting."
    exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
    print_err "Docker is required but not installed. Please install Docker first."
    exit 1
fi

if docker compose version >/dev/null 2>&1; then
    DOCKER_CMD="docker compose"
elif docker-compose version >/dev/null 2>&1; then
    DOCKER_CMD="docker-compose"
else
    print_err "Docker Compose is not installed. Aborting."
    exit 1
fi
print_success "All prerequisites met ($DOCKER_CMD found)."

# ==============================================================================
# 2. DOWNLOAD ASSETS
# ==============================================================================
print_step "Creating workspace..."
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"
print_info "Working directory: $(pwd)"

print_step "Fetching deployment files..."
curl -sSfL "$COMPOSE_FILE_URL" -o docker-compose.yml || { print_err "Failed to download docker-compose.yml"; exit 1; }
curl -sSfL "$ENV_EXAMPLE_URL" -o .env || { print_err "Failed to download .env.example"; exit 1; }
curl -sSfL "$README_URL" -o README.md || { print_warn "Failed to download local README.md, skipping."; }
print_success "Files downloaded successfully."

# ==============================================================================
# 3. INTERACTIVE CONFIGURATION
# ==============================================================================
print_step "Environment Configuration"
print_info "We need to set up a few critical security parameters for your Gateway."
echo ""

# --- ADMIN_MASTER_KEY ---
print_info "${C_CYAN}[1/3] Admin Console Master Key${C_RESET}"
print_info "This key is required to access the central Admin Dashboard (/admin.html)."
print_info "It protects your cluster registrations and global fleet visibility."
while true; do
    read -rp "    Enter a strong master key (e.g., a long password): " ADMIN_KEY
    if [[ -n "$ADMIN_KEY" ]]; then
        break
    else
        print_warn "The Admin Master Key cannot be empty."
    fi
done
echo ""

# --- ENCRYPTION_KEY ---
print_info "${C_CYAN}[2/3] Database Encryption Key${C_RESET}"
print_info "The Gateway encrypts all sensitive Kubernetes tokens inside its SQLite database using AES (Fernet)."
print_warn "NEVER change this key after the first setup, or you will lose access to all registered clusters."
print_info "If you leave this blank, the platform will auto-generate a secure key and save it in 'data/.encryption_key'."
read -rp "    Provide a custom 32-byte base64 Fernet key [Press ENTER to auto-generate]: " ENC_KEY
echo ""

# --- JWT_SECRET_KEY ---
print_info "${C_CYAN}[3/3] JWT Session Key${C_RESET}"
print_info "This key signs the browser cookies for logged-in users."
print_info "If left blank, a volatile key is generated on boot (users will be logged out if the container restarts)."
read -rp "    Provide a custom JWT Secret [Press ENTER for volatile sessions]: " JWT_KEY
echo ""

# ==============================================================================
# 4. APPLY CONFIGURATION
# ==============================================================================
print_step "Applying configuration..."

# Replace placeholders in the .env file using sed
sed -i.bak "s|^ADMIN_MASTER_KEY=.*|ADMIN_MASTER_KEY=${ADMIN_KEY}|" .env
if [[ -n "$ENC_KEY" ]]; then
    sed -i.bak "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=${ENC_KEY}|" .env
fi
if [[ -n "$JWT_KEY" ]]; then
    sed -i.bak "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=${JWT_KEY}|" .env
fi
rm -f .env.bak
print_success ".env file generated and secured."

# ==============================================================================
# 5. BOOTSTRAP
# ==============================================================================
print_step "Starting the Control Plane..."
$DOCKER_CMD up -d

# ==============================================================================
# 6. ONBOARDING GUIDE
# ==============================================================================
echo -e "\n${C_GREEN}======================================================================${C_RESET}"
echo -e "${C_GREEN} 🎉 GATEWAY SUCCESSFULLY DEPLOYED!${C_RESET}"
echo -e "${C_GREEN}======================================================================${C_RESET}\n"

echo -e "Dashboard URL : ${C_CYAN}http://localhost${C_RESET}"
echo -e "Admin Console : ${C_CYAN}http://localhost/admin.html${C_RESET}"
echo -e "Admin Key     : ${C_YELLOW}${ADMIN_KEY}${C_RESET}\n"

echo -e "${C_BLUE}--- NEXT STEPS: REGISTER YOUR FIRST CLUSTER ---${C_RESET}"
echo -e "To manage a cluster, the Gateway needs a Service Account and the cluster CA."
echo -e "Run these commands on your target Kubernetes cluster to get started:\n"

echo -e "${C_YELLOW}1. Extract the Cluster CA Certificate (ca.crt):${C_RESET}"
echo -e "   kubectl config view --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 --decode > ca.crt"
echo -e "   ${C_CYAN}# Note: Upload this ca.crt file in the Admin Console.${C_RESET}\n"

echo -e "${C_YELLOW}2. Create the Admin Service Account & Binding:${C_RESET}"
echo -e "   kubectl create namespace k8s-gateway"
echo -e "   kubectl create serviceaccount gateway-admin -n k8s-gateway"
echo -e "   kubectl create clusterrolebinding gateway-admin-binding --clusterrole=cluster-admin --serviceaccount=k8s-gateway:gateway-admin\n"

echo -e "${C_YELLOW}3. Generate the Long-Lived Token:${C_RESET}"
echo -e "   kubectl create token gateway-admin -n k8s-gateway --duration=87600h"
echo -e "   ${C_CYAN}# Note: Copy the output token. In the Admin Console, create a profile named 'admin' and paste this token.${C_RESET}\n"

echo -e "For advanced setups, custom RBAC profiles, or architecture details,"
echo -e "please refer to the official documentation."
echo -e "${C_GREEN}Happy routing! ☸️${C_RESET}\n"