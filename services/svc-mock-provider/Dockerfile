FROM amplifier-service-base

COPY services/svc-mock-provider/ /build/svc-mock-provider/
RUN cd /build/svc-mock-provider && uv pip install --system . && rm -rf /build

CMD ["uvicorn", "svc_mock_provider.app:app", "--host", "0.0.0.0", "--port", "8000"]
