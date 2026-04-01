# ── Stage 1: Shared Amplifier service base ────────────────────────────────
FROM python:3.12-slim AS amplifier-service-base
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY amplifier-service-sdk/ /build/amplifier-service-sdk/
RUN cd /build/amplifier-service-sdk && uv pip install --system . && rm -rf /build
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"
EXPOSE 8000

# ── Stage 2: svc-filesystem ────────────────────────────────────────────
FROM amplifier-service-base
# Copy SDK to the path [tool.uv.sources] expects: ../../amplifier-service-sdk
# from /build/svc-filesystem/ resolves to /amplifier-service-sdk/
COPY amplifier-service-sdk/ /amplifier-service-sdk/
COPY services/svc-filesystem/ /build/svc-filesystem/
RUN cd /build/svc-filesystem && uv pip install --system . && rm -rf /build /amplifier-service-sdk

CMD ["uvicorn", "svc_filesystem.app:app", "--host", "0.0.0.0", "--port", "8000"]
