# ── Stage 1: Shared Amplifier service base ────────────────────────────────
FROM python:3.12-slim AS amplifier-service-base
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY amplifier-service-sdk/ /build/amplifier-service-sdk/
RUN cd /build/amplifier-service-sdk && uv pip install --system . && rm -rf /build
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"
EXPOSE 8000

# ── Stage 2: svc-machine ───────────────────────────────────────────────
FROM amplifier-service-base
RUN apt-get update && apt-get install -y ripgrep openssh-client && rm -rf /var/lib/apt/lists/*
# Copy SDK to the path [tool.uv.sources] expects: ../../amplifier-service-sdk
# from /build/svc-machine/ resolves to /amplifier-service-sdk/
COPY amplifier-service-sdk/ /amplifier-service-sdk/
COPY services/svc-machine/ /build/svc-machine/
RUN cd /build/svc-machine && uv pip install --system . && rm -rf /build /amplifier-service-sdk

ENV WORKSPACE_DIR=/workspace

CMD ["uvicorn", "svc_machine.service:app", "--host", "0.0.0.0", "--port", "8000"]
