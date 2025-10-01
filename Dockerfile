# Ubuntu 24.04 base image
FROM ubuntu:24.04

# Install dependencies
RUN apt-get update && \
    apt-get install -y \
    openjdk-21-jdk \
    python3 \
    python3-pip \
    curl \
    unzip \
    wget \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set JAVA_HOME for OpenJDK 21
ENV JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
ENV PATH=$JAVA_HOME/bin:$PATH

# Download and install Joern via the official script
WORKDIR /opt
RUN curl -L https://github.com/joernio/joern/releases/download/v4.0.424/joern-install.sh -o joern-install.sh && \
    chmod +x joern-install.sh && \
    ./joern-install.sh && \
    rm joern-install.sh

# Add Joern to PATH
ENV PATH="/opt/joern:$PATH"

# Default working directory
WORKDIR /workspace

# Default command: start Joern shell
CMD ["joern"]
