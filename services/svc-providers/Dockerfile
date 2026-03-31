FROM amplifier-service-base

COPY services/svc-providers/ /build/svc-providers/
RUN cd /build/svc-providers && uv pip install --system . && rm -rf /build

CMD ["uvicorn", "svc_providers.app:app", "--host", "0.0.0.0", "--port", "8000"]
