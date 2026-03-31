FROM amplifier-service-base

COPY . .
RUN pip install .

CMD ["uvicorn", "svc_hooks_shell.app:app", "--host", "0.0.0.0", "--port", "8000"]
