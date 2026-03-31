FROM python:3.11-slim
WORKDIR /app
RUN pip install uv==0.10.12
COPY pyproject.toml .
COPY src/ src/
RUN uv pip install --system -e .
EXPOSE 8080
CMD ["uvicorn", "svc_modes.app:app", "--host", "0.0.0.0", "--port", "8080"]
