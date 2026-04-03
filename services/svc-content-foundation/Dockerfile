# ── Stage 1: Shared Amplifier service base ────────────────────────────────────
FROM python:3.12-slim AS amplifier-service-base
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY amplifier-service-sdk/ /build/amplifier-service-sdk/
RUN cd /build/amplifier-service-sdk && uv pip install --system . && rm -rf /build
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"
EXPOSE 8000

# ── Stage 2: svc-content-foundation ───────────────────────────────────────────
FROM amplifier-service-base

COPY services/svc-content-foundation/describe.yaml /app/describe.yaml
COPY services/svc-content-foundation/content/ /app/content/

CMD ["amplifier-serve", "--config", "/app/describe.yaml"]
