FROM amplifier-service-base

# Copy service configuration
COPY services/svc-content-recipes/describe.yaml /app/describe.yaml

# Copy content from amplifier-recipes context directory
COPY services/amplifier-recipes/src/amplifier_recipes/context/ /app/content/

CMD ["amplifier-serve", "--config", "/app/describe.yaml"]
