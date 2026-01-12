#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Configuration
REGISTRY="${REGISTRY:-ztsyed}"
IMAGE_NAME="${IMAGE_NAME:-afk}"
TAG="${TAG:-$(date +%Y%m%d-%H%M%S)}"
NAMESPACE="${NAMESPACE:-default}"
RELEASE_NAME="${RELEASE_NAME:-afk}"
# Target platform: desk.morton.local is AMD64
PLATFORM="${PLATFORM:-linux/amd64}"

FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${TAG}"

cd "${PROJECT_DIR}"

echo "============================================"
echo "AFK Build and Deploy"
echo "============================================"
echo "Image: ${FULL_IMAGE}"
echo "Platform: ${PLATFORM}"
echo "Namespace: ${NAMESPACE}"
echo "============================================"

# Step 1: Build for ARM64
echo ""
echo "[1/3] Building Docker image for ${PLATFORM}..."
docker build --platform "${PLATFORM}" -t "${FULL_IMAGE}" .
docker tag "${FULL_IMAGE}" "${REGISTRY}/${IMAGE_NAME}:latest"

# Step 2: Push
echo ""
echo "[2/3] Pushing to Docker Hub..."
docker push "${FULL_IMAGE}"
docker push "${REGISTRY}/${IMAGE_NAME}:latest"

# Step 3: Deploy
echo ""
echo "[3/3] Deploying to Kubernetes..."
helm upgrade --install "${RELEASE_NAME}" "${PROJECT_DIR}/k8s/helm/afk" \
    -n "${NAMESPACE}" \
    --create-namespace \
    --set image.tag="${TAG}" \
    --wait \
    "$@"

echo ""
echo "============================================"
echo "Deployment complete!"
echo "============================================"
echo ""
echo "Image: ${FULL_IMAGE}"
echo "URL: https://afk.ziasyed.com"
echo ""
echo "Commands:"
echo "  kubectl get pods -n ${NAMESPACE} -l app.kubernetes.io/name=afk"
echo "  kubectl logs -n ${NAMESPACE} -l app.kubernetes.io/name=afk -f"
