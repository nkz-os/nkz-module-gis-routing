# Multi-stage build for Backend
# Stage 1: Build Fields2Cover (C++17 + SWIG Python bindings) + pip deps.
FROM python:3.11-slim AS builder

WORKDIR /app

# Fields2Cover build dependencies (canonical list from upstream docs/CI).
# OR-Tools is auto-fetched by F2C's CMake (release tarball, amd64) at configure.
ARG F2C_VERSION=v2.0.0
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates cmake g++ git \
    libeigen3-dev libgdal-dev libpython3-dev python3 python3-pip \
    libgtest-dev libtbb-dev swig libgeos-dev gnuplot \
    libtinyxml2-dev nlohmann-json3-dev libproj-dev \
    && rm -rf /var/lib/apt/lists/*

# Build + install Fields2Cover. Installs to /usr/local (lib + python module).
RUN git clone --depth 1 --branch ${F2C_VERSION} --recurse-submodules \
      https://github.com/Fields2Cover/Fields2Cover.git /tmp/f2c \
    && cmake -S /tmp/f2c -B /tmp/f2c/build \
      -DCMAKE_BUILD_TYPE=Release -DBUILD_PYTHON=ON -DBUILD_TESTS=OFF -DBUILD_DOC=OFF \
    && cmake --build /tmp/f2c/build -j"$(nproc)" \
    && cmake --install /tmp/f2c/build \
    && rm -rf /tmp/f2c

# Python application dependencies (installed to /root/.local via --user).
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Production image.
FROM python:3.11-slim

WORKDIR /app

# Runtime shared libraries. The -dev packages pull the correct sonames plus
# GDAL's large transitive dependency set without hand-guessing package names
# (robustness over image size). gnuplot is an optional F2C plotting backend.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal-dev libtbb-dev libgeos-dev libtinyxml2-dev libproj-dev \
    libgomp1 gnuplot \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user first.
RUN useradd -m -u 1000 appuser

# Fields2Cover native libs (libFields2Cover.so + bundled OR-Tools/absl .so).
COPY --from=builder /usr/local/lib/ /usr/local/lib/
# Fields2Cover Python binding (SWIG wrapper + extension module).
COPY --from=builder /usr/local/lib/python3.11/site-packages/fields2cover.py \
                    /usr/local/lib/python3.11/site-packages/
COPY --from=builder /usr/local/lib/python3.11/site-packages/_fields2cover_python.so \
                    /usr/local/lib/python3.11/site-packages/
RUN ldconfig

# Copy pip packages installed in the builder.
COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local

# Copy application code.
COPY --chown=appuser:appuser app/ ./app/

# Switch to non-root user.
USER appuser

# Set PATH to include user-installed packages.
ENV PATH=/home/appuser/.local/bin:$PATH

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health')" || exit 1

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
