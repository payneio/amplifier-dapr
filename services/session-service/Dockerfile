FROM amplifier-service-base

COPY services/session-service/ /build/session-service/
RUN cd /build/session-service && uv pip install --system . && rm -rf /build

CMD ["uvicorn", "session_service.app:app", "--host", "0.0.0.0", "--port", "8000"]
