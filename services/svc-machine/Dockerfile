FROM amplifier-service-base

COPY services/svc-machine/ /build/svc-machine/
RUN cd /build/svc-machine && uv pip install --system . && rm -rf /build

ENV WORKSPACE_DIR=/workspace

CMD ["uvicorn", "svc_machine.service:app", "--host", "0.0.0.0", "--port", "8000"]
