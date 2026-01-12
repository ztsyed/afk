#!/bin/bash
# Tail AFK server logs from k3s

NAMESPACE="${NAMESPACE:-default}"
POD_LABEL="app.kubernetes.io/name=afk"

echo "Tailing AFK logs..."
echo "Press Ctrl+C to stop"
echo "========================================"

kubectl logs -n "${NAMESPACE}" -l "${POD_LABEL}" -f --tail=100 "$@"
