FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim@sha256:f106758c361464e22aa1946c1338ae94de22ec784943494f26485d345dac2d85

ENV UV_COMPILE_BYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    apt-utils \
    bash \
    build-essential \
    ca-certificates \
    curl \
    git \
    zip \
    unzip \
    net-tools \
    dnsutils \
    htop \
    lsof \
    strace \
    gnupg \
    less \
    openssh-client \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN gpg --keyserver hkps://keyserver.ubuntu.com --recv-keys A6310ACC4672475C && \
    curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" && \
    curl -o awscliv2.sig https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip.sig && \
    gpg --verify awscliv2.sig awscliv2.zip && \
    unzip awscliv2.zip && \
    ./aws/install && \
    rm -rf awscliv2.zip awscliv2.sig aws

# Install ClearML packages
RUN uv pip install --system --no-cache clearml clearml-agent