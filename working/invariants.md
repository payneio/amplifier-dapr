Current System Invariants

1. Service names are deterministic hashes. svc-{role}-{sha256(source_key)[:8]}. Same build path for the same role always produces the same name. This is
the deduplication mechanism.

2. Services are shared across agents automatically. If two agents define bash with the same build: ./services/svc-bash, they get the same container. The
compose generator deduplicates by service name. The service-map records which app-id each agent uses for each role, but those app-ids can (and do) point
to the same container.

3. One session-service, many agents. Session-service is a singleton (never hashed, always session-service). It handles ALL agents. It reads the agent
definition + service-map to build the routing table for whichever agent the client requests.

4. The routing table is built per-turn, per-agent. At each turn, session-service calls get_agent_config(agent_ref) → gets that agent's service app-ids →
discovers them via Dapr /describe → builds a RoutingTable. Different agents get different routing tables.

5. The orchestrator is stateless — it uses the routing table for ALL dispatch. Tools, providers, hooks, context — every app-id comes from the routing
table passed to it. Zero hardcoded names in the orchestrator.

6. Tool services DON'T participate in the routing table. The orchestrator calls tools via routing table, but when a tool service needs to call another
service (e.g., bash → machine), it makes its own Dapr call with a hardcoded name. This is the gap.

7. ampctl operates against ~/.amplifier/, not any project directory. It can be run from any pwd. It writes the service-map to
~/.amplifier/service-map.yaml.

8. Dapr sidecars use the hashed name as their app-id. --app-id=svc-bash-8758a015. This is the name other services must use for Dapr service invocation.

9. Tool services are per-role, not per-agent. A single svc-bash-8758a015 container serves bash requests for ALL agents. It doesn't know which agent it's
serving. It just needs to reach machine.