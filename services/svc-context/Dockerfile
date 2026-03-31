FROM amplifier-service-base

COPY services/svc-context/ /build/svc-context/
RUN cd /build/svc-context && uv pip install --system . && rm -rf /build

CMD ["uvicorn", "svc_context.app:app", "--host", "0.0.0.0", "--port", "8000"]
