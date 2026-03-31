FROM python:3.11-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Copy project files
COPY pyproject.toml .
COPY src/ src/

# Install dependencies
RUN uv pip install --system -e .

EXPOSE 8080

CMD ["uvicorn", "svc_search.app:app", "--host", "0.0.0.0", "--port", "8080"]
