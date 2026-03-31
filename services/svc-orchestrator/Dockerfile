FROM amplifier-service-base

COPY services/svc-orchestrator/ /build/svc-orchestrator/
RUN cd /build/svc-orchestrator && uv pip install --system . && rm -rf /build

CMD ["uvicorn", "svc_orchestrator.app:app", "--host", "0.0.0.0", "--port", "8000"]
