# Platform-independent run of this experiment: docker build + docker run (see README).
# Every input is pinned: base images by digest, Debian packages by version from a dated
# snapshot.debian.org archive, uv by version + digest, Python + packages by uv.lock.

# uv 0.10.11 (same version used to create uv.lock)
FROM ghcr.io/astral-sh/uv:0.10.11@sha256:3472e43b4e738cf911c99d41bb34331280efad54c73b1def654a6227bb59b2b4 AS uv

# Debian 12 (bookworm) slim, dated tag 20260918; digest of the multi-arch index
FROM debian:bookworm-20260918-slim@sha256:3783cc01769c7b2b1b83a5c5ad96c815348e28ed7da68e2e3687004faa906251

# Resolve apt packages from a frozen snapshot so the compiler version cannot drift.
RUN rm -f /etc/apt/sources.list.d/debian.sources \
 && echo "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/20260918T000000Z bookworm main" \
      > /etc/apt/sources.list.d/snapshot.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      gfortran=4:12.2.0-3 gfortran-12=12.2.0-14+deb12u1 \
      gcc=4:12.2.0-3 gcc-12=12.2.0-14+deb12u1 \
      libgfortran5=12.2.0-14+deb12u1 \
      ca-certificates=20230311+deb12u1 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/
ENV UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    MPLBACKEND=Agg

WORKDIR /work
# Lock first so the environment layer is cached independently of the scripts.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked
COPY . .
CMD ["./run.sh"]
