FROM amplifier-service-base

COPY services/svc-bash/ /build/svc-bash/
RUN cd /build/svc-bash && uv pip install --system . && rm -rf /build

CMD ["uvicorn", "svc_bash.app:app", "--host", "0.0.0.0", "--port", "8000"]
