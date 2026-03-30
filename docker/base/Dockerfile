FROM python:3.12-slim

WORKDIR /app

# Install uv package manager
RUN pip install --no-cache-dir uv

# Copy and install the Amplifier Service SDK system-wide, then clean up build artefacts
COPY amplifier-service-sdk/ /build/amplifier-service-sdk/
RUN cd /build/amplifier-service-sdk && uv pip install --system . && rm -rf /build

# Health check: use Python's urllib to probe the /healthz endpoint
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"

EXPOSE 8000
