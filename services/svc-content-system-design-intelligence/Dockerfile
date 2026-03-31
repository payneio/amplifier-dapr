FROM amplifier-service-base

# Copy service configuration
COPY services/svc-content-system-design-intelligence/describe.yaml /app/describe.yaml

# Copy content from amplifier-system-design-intelligence src directory (no context/ dir exists)
COPY services/amplifier-system-design-intelligence/src/amplifier_system_design_intelligence/ /app/content/

CMD ["amplifier-serve", "--config", "/app/describe.yaml"]
