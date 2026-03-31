FROM amplifier-service-base

# Copy service configuration
COPY services/svc-content-browser-tester/describe.yaml /app/describe.yaml

# Copy content from amplifier-browser-tester context directory
COPY services/amplifier-browser-tester/src/amplifier_browser_tester/context/ /app/content/

CMD ["amplifier-serve", "--config", "/app/describe.yaml"]
