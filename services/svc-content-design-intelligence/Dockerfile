FROM amplifier-service-base

# Copy service configuration
COPY services/svc-content-design-intelligence/describe.yaml /app/describe.yaml

# Copy content from amplifier-design-intelligence context directory
COPY services/amplifier-design-intelligence/src/amplifier_design_intelligence/context/ /app/content/

CMD ["amplifier-serve", "--config", "/app/describe.yaml"]
