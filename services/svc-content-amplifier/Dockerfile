FROM amplifier-service-base

# Copy service configuration
COPY services/svc-content-amplifier/describe.yaml /app/describe.yaml

# Copy content from amplifier-amplifier context directory
COPY services/amplifier-amplifier/src/amplifier_amplifier/context/ /app/content/

CMD ["amplifier-serve", "--config", "/app/describe.yaml"]
