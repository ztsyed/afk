#!/bin/bash
set -e

# Configuration
REGISTRY="${REGISTRY:-ztsyed}"
IMAGE_NAME="${IMAGE_NAME:-afk}"
TAG="${TAG:-latest}"
# Target platform: desk.morton.local is AMD64
PLATFORM="${PLATFORM:-linux/amd64}"

FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${TAG}"

echo "Building ${FULL_IMAGE} for ${PLATFORM}..."

# Build the Docker image for target platform
docker build --platform "${PLATFORM}" -t "${FULL_IMAGE}" .

echo "Build complete: ${FULL_IMAGE}"

# Optionally push
if [[ "${PUSH:-false}" == "true" ]]; then
    echo "Pushing ${FULL_IMAGE}..."
    docker push "${FULL_IMAGE}"
    echo "Push complete!"
fi
