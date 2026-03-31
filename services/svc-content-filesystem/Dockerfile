FROM amplifier-service-base

# Copy service configuration
COPY services/svc-content-filesystem/describe.yaml /app/describe.yaml

# Copy content from amplifier-filesystem context directory
COPY services/amplifier-filesystem/src/amplifier_filesystem/context/ /app/content/

CMD ["amplifier-serve", "--config", "/app/describe.yaml"]
