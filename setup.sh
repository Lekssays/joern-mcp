#!/bin/bash
# Setup script for Joern MCP Server
# This script builds the Joern Docker image and starts Redis

set -e

echo "🕷️  Setting up Joern MCP Server..."
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker and try again."
    exit 1
fi

# Build Joern image
echo "🏗️  Building Joern Docker image..."
docker build -f Dockerfile.joern -t joern:latest . --progress=plain

# Verify the image was built
if docker images | grep -q "joern.*latest"; then
    echo "✅ Joern image built successfully!"
else
    echo "❌ Failed to build Joern image"
    exit 1
fi

echo ""

# Start Redis
echo "🚀 Starting Redis container..."

# Check if Redis container already exists
if docker ps -a --format '{{.Names}}' | grep -q "^joern-redis$"; then
    echo "ℹ️  Redis container already exists"
    
    # Check if it's running
    if docker ps --format '{{.Names}}' | grep -q "^joern-redis$"; then
        echo "✅ Redis is already running"
    else
        echo "▶️  Starting existing Redis container..."
        docker start joern-redis
        echo "✅ Redis started"
    fi
else
    # Create and start new Redis container
    docker run -d \
        --name joern-redis \
        -p 6379:6379 \
        --restart unless-stopped \
        redis:7-alpine
    echo "✅ Redis container created and started"
fi

echo ""

# Test Redis connection
echo "🔍 Testing Redis connection..."
if docker exec joern-redis redis-cli ping > /dev/null 2>&1; then
    echo "✅ Redis is responding"
else
    echo "⚠️  Redis may not be ready yet, give it a few seconds"
fi

echo ""
echo "═══════════════════════════════════════════"
echo "✅ Setup complete!"
echo "═══════════════════════════════════════════"
echo ""
echo "📊 Image sizes:"
docker images joern:latest redis:7-alpine --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"
echo ""
echo "🚀 Next steps:"
echo "   1. (Optional) Configure: cp config.example.yaml config.yaml"
echo "   2. Run server: python main.py"
echo "   3. Server will be available at http://localhost:4242"
echo ""
