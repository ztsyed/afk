#!/bin/bash
set -e

# Configuration
NAMESPACE="${NAMESPACE:-default}"
RELEASE_NAME="${RELEASE_NAME:-afk}"
CHART_PATH="$(dirname "$0")/../k8s/helm/afk"

echo "Deploying AFK to namespace: ${NAMESPACE}"

# Check if release exists
if helm status "${RELEASE_NAME}" -n "${NAMESPACE}" &>/dev/null; then
    echo "Upgrading existing release..."
    helm upgrade "${RELEASE_NAME}" "${CHART_PATH}" \
        -n "${NAMESPACE}" \
        --wait \
        "$@"
else
    echo "Installing new release..."
    helm install "${RELEASE_NAME}" "${CHART_PATH}" \
        -n "${NAMESPACE}" \
        --create-namespace \
        --wait \
        "$@"
fi

echo "Deployment complete!"
echo ""
echo "To check status:"
echo "  kubectl get pods -n ${NAMESPACE} -l app.kubernetes.io/name=afk"
echo ""
echo "To view logs:"
echo "  kubectl logs -n ${NAMESPACE} -l app.kubernetes.io/name=afk -f"
