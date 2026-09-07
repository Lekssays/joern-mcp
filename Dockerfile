# Joern CLI container for CPG generation and caching.
# NOTE: base image is noble (Ubuntu 24.04, glibc 2.39), NOT jammy (22.04,
# glibc 2.35). rust2cpg's native astgen binary (rust_ast_gen-linux) is linked
# against GLIBC_2.39 and fails on jammy with "version `GLIBC_2.39' not found",
# silently yielding an empty Rust CPG. glibc is backward-compatible, so every
# other frontend's native astgen keeps working on noble.
FROM eclipse-temurin:21-jdk-noble

# Link the GHCR package to this repository for GitHub Actions GITHUB_TOKEN access.
LABEL org.opencontainers.image.source="https://github.com/NguyenThanhHungDev140503/codebadger"

RUN apt-get update && apt-get install -y \
    curl \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

ENV JOERN_VERSION=4.0.594
ENV JOERN_HOME=/opt/joern

RUN mkdir -p ${JOERN_HOME} && \
    cd /tmp && \
    # Download joern-cli.zip directly (the install script's URL omits the 'v' prefix)
    echo "Downloading Joern v${JOERN_VERSION} (~500MB, this may take a while)..." && \
    wget -q --show-progress --retry-connrefused --tries=10 \
        -O joern-cli.zip \
        "https://github.com/joernio/joern/releases/download/v${JOERN_VERSION}/joern-cli-linux-x86_64.zip" && \
    echo "Extracting..." && \
    unzip -qo joern-cli.zip -d ${JOERN_HOME} && \
    rm joern-cli.zip && \
    echo "Joern v${JOERN_VERSION} installed successfully."

ENV PATH="${JOERN_HOME}/joern-cli:${JOERN_HOME}/joern-cli/bin:${PATH}"

# Rust toolchain — rust2cpg's native astgen loads the crate by shelling out to
# `cargo`/`rustc` (it errors "Are `cargo` and `rustc` on your PATH?" otherwise),
# so without them every Rust CPG comes out empty. The minimal profile installs
# just rustc + cargo (no docs/clippy/rustfmt) to keep the layer small.
ENV RUSTUP_HOME=/opt/rustup \
    CARGO_HOME=/opt/cargo
RUN curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable \
    && rm -rf /opt/rustup/downloads /opt/rustup/tmp /opt/rustup/toolchains/*/share/doc /opt/rustup/toolchains/*/share/man
ENV PATH="/opt/cargo/bin:${PATH}"

RUN mkdir -p /playground

RUN joern --help && rustc --version && cargo --version

RUN echo '#!/bin/bash\n\
set -e\n\
tail -f /dev/null\n\
' > /entrypoint.sh && chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
