FROM amplifier-service-base

# Copy service configuration
COPY services/svc-content-superpowers/describe.yaml /app/describe.yaml

# Copy content from amplifier-superpowers context directory
COPY services/amplifier-superpowers/src/amplifier_superpowers/context/ /app/content/

CMD ["amplifier-serve", "--config", "/app/describe.yaml"]
