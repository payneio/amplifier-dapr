FROM amplifier-service-base

# Copy service configuration
COPY services/svc-content-core/describe.yaml /app/describe.yaml

# Copy content from amplifier-core context directory
COPY services/amplifier-core/src/amplifier_core/context/ /app/content/

CMD ["amplifier-serve", "--config", "/app/describe.yaml"]
