#!/bin/bash
# Build script for Joern Docker image

set -e

echo "🏗️  Building Joern Docker image..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker and try again."
    exit 1
fi

# Build the image
echo "📦 Building joern:latest image..."
docker build -f Dockerfile.joern -t joern:latest . --progress=plain

# Verify the image was built
if docker images | grep -q "joern.*latest"; then
    echo "✅ Joern image built successfully!"
    echo "📊 Image size:"
    docker images joern:latest --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"
else
    echo "❌ Failed to build Joern image"
    exit 1
fi

echo ""
echo "🚀 Ready to run the Joern MCP Server!"
echo "   Usage: python main.py"
echo ""