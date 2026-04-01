# Using Providers in Amplifier IPC

Providers are the LLM backends that power Amplifier IPC sessions. This guide
covers how to configure, select, and extend providers.

## Quick Start

Set an API key and start a session:

```bash
# Store your API key securely
export ANTHROPIC_API_KEY="sk-ant-..."

# Start the stack
docker compose up

# Run a session
amplifier-ipc run "Hello, world"
```

The default agent definition uses Anthropic. If your key is set, sessions
just work.

## Available Providers

All providers live in the `svc-providers` service (`services/svc-providers/`).
A separate `svc-mock-provider` service (`services/svc-mock-provider/`) provides
a deterministic mock for testing.

| Provider | Name | Key Env Var | Notes |
|----------|------|-------------|-------|
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` | Default. Full-featured: retry, rate-limit tracking, tool repair, prompt caching, thinking. |
| OpenAI | `openai` | `OPENAI_API_KEY` | Supports reasoning_effort. |
| Azure OpenAI | `azure_openai` | `AZURE_OPENAI_API_KEY` | Extends OpenAI. Supports Azure AD token fallback. |
| Google Gemini | `gemini` | `GOOGLE_API_KEY` or `GEMINI_API_KEY` | Thinking budget support. |
| Ollama | `ollama` | `OLLAMA_HOST` (optional) | Local models. No API key required. |
| vLLM | `vllm` | `VLLM_API_KEY` (optional) | Extends OpenAI. Points at a vLLM server. |
| GitHub Copilot | `github_copilot` | `GITHUB_TOKEN` or `GH_TOKEN` | Token exchange flow. Extends OpenAI. |

The mock provider is in its own service (`svc-mock-provider`) for test
isolation and does not require an API key.

## How Providers Work

### Architecture Overview

```
CLI (amplifier-ipc)
  |
  |  HTTP/SSE
  v
session-service (gateway)
  |
  v
svc-orchestrator (agent loop)
  |  Dapr service invocation: POST /providers/{name}/complete
  v
svc-providers (FastAPI)
  |  Selects provider instance by name
  |  Calls provider.complete(ChatRequest) -> ChatResponse
  v
LLM API (Anthropic, OpenAI, etc.)
```

Providers communicate over **HTTP via Dapr service invocation**. The
orchestrator calls `svc-providers` (or `svc-mock-provider`) by posting to
`POST /providers/{name}/complete`. Each provider runs as an independent
container -- a provider crash won't take down the orchestrator or any other
service.

### The Provider Endpoint

Each provider exposes a completion endpoint:

```
POST /providers/{name}/complete
```

The request body is a `ChatRequest` (messages, tools, system prompt,
temperature, etc.) and the response is a `ChatResponse` (content blocks,
tool calls, usage, etc.).

The `svc-providers` service routes to the correct provider implementation
based on the `{name}` path parameter.

## Configuration

Provider configuration flows through multiple layers with clear precedence.

### API Keys

API keys are passed as environment variables to the `svc-providers` container.
In local development, set them in your shell or in a `.env` file loaded by
Docker Compose:

```bash
# Shell environment
export ANTHROPIC_API_KEY="sk-ant-..."

# Or in .env (loaded by docker compose)
ANTHROPIC_API_KEY=sk-ant-...
```

**Security note:** Never store raw API keys in settings files or definition
YAMLs. Always use environment variables.

### Provider Selection

The agent definition specifies which provider to use:

```yaml
# In a behavior YAML
provider: anthropic
```

The session-service resolves this and tells the orchestrator which provider
endpoint to call.

### Config Keys by Provider

Each provider reads specific configuration from environment variables:

**Anthropic:**
| Key | Default | Env Var |
|-----|---------|---------|
| `api_key` | -- | `ANTHROPIC_API_KEY` |
| `model` | `claude-sonnet-4-20250514` | -- |
| `max_tokens` | `16384` | -- |

**OpenAI:**
| Key | Default | Env Var |
|-----|---------|---------|
| `api_key` | -- | `OPENAI_API_KEY` |
| `model` | `gpt-4o` | -- |
| `max_tokens` | `16384` | -- |

**Azure OpenAI:**
| Key | Default | Env Var |
|-----|---------|---------|
| `api_key` | -- | `AZURE_OPENAI_API_KEY` |
| `azure_endpoint` | -- | `AZURE_OPENAI_ENDPOINT` |
| `api_version` | `2024-12-01-preview` | `AZURE_OPENAI_API_VERSION` |

**Gemini:**
| Key | Default | Env Var |
|-----|---------|---------|
| `api_key` | -- | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| `model` | `gemini-2.0-flash` | -- |
| `max_tokens` | `8192` | -- |

**Ollama:**
| Key | Default | Env Var |
|-----|---------|---------|
| `host` | `http://localhost:11434` | `OLLAMA_HOST` |
| `model` | `llama3.2` | -- |

**vLLM:**
| Key | Default | Env Var |
|-----|---------|---------|
| `base_url` | -- | `VLLM_API_BASE` |
| `api_key` | -- | `VLLM_API_KEY` |

**GitHub Copilot:**
| Key | Default | Env Var |
|-----|---------|---------|
| `token` | -- | `GITHUB_TOKEN` or `GH_TOKEN` |
| `model` | `gpt-4o` | -- |

## Routing Matrix

The routing matrix maps semantic **roles** (like `coding`, `reasoning`, `fast`)
to specific provider/model combinations. This lets sub-agents request the right
kind of model without hardcoding provider names.

The routing matrix is implemented as a pre-hook in `svc-hooks-routing`. It
intercepts provider requests via Dapr service invocation and resolves
`model_role` to a concrete provider+model pair.

### Matrix Files

Matrices live in `~/.amplifier/routing/` as YAML files:

```yaml
# ~/.amplifier/routing/balanced.yaml
name: balanced
roles:
  general:
    provider: anthropic
    model: claude-sonnet-4-20250514
    description: Versatile catch-all
  fast:
    provider: anthropic
    model: claude-haiku-3-5
    description: Quick utility tasks
  coding:
    provider: anthropic
    model: claude-sonnet-4-20250514
    description: Code generation and debugging
  reasoning:
    provider: anthropic
    model: claude-opus-4
    description: Deep architectural reasoning
```

## Adding a New Provider

### Step 1: Create the Provider Module

Add a new file in `services/svc-providers/src/svc_providers/providers/`:

```python
# services/svc-providers/src/svc_providers/providers/my_provider.py

from __future__ import annotations

import os
from typing import Any

from amplifier_service_sdk import ChatRequest, ChatResponse


class MyProvider:
    """My custom LLM provider."""

    name = "my_provider"

    def __init__(self) -> None:
        self.api_key = os.environ.get("MY_PROVIDER_API_KEY")
        self.model = "default-model"
        if not self.api_key:
            raise ValueError("MY_PROVIDER_API_KEY not set")

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        # 1. Convert request.messages to vendor format
        # 2. Call the LLM API
        # 3. Convert response to ChatResponse
        ...
```

### Step 2: Register the Route

Add the provider route to the FastAPI app in `svc-providers` so it is
available at `POST /providers/my_provider/complete`.

### Step 3: Add SDK Dependency

Edit `services/svc-providers/pyproject.toml`:

```toml
dependencies = [
    "amplifier-service-sdk",
    "my-provider-sdk",   # <-- add your SDK
    # ... existing deps
]
```

### Step 4: Add to Docker Compose

Add a service entry (or extend the existing `svc-providers` image) and
pass `MY_PROVIDER_API_KEY` as an environment variable.

### Provider Implementation Patterns

Follow these patterns from the existing providers:

1. **Lazy client initialization** -- use a `@property` that imports the SDK on
   first access. This avoids import-time failures when the SDK is missing.

2. **Message conversion** -- implement `_convert_messages()` to translate
   Amplifier's message format to the vendor's format.

3. **Tool conversion** -- implement `_convert_tools_from_request()` to translate
   `ToolSpec` objects to the vendor's function-calling format.

4. **Response conversion** -- implement `_convert_to_chat_response()` to produce
   a `ChatResponse` with proper content blocks, tool calls, and usage info.

5. **Error handling** -- use retry logic for transient API errors. See
   the Anthropic provider for a reference implementation.

## Troubleshooting

### Provider container not starting

Check Docker Compose logs for the provider service:

```bash
docker compose logs svc-providers
```

Common causes: missing API key env var, SDK import error, port conflict.

### API key not working

- Verify the env var is set in the container: check your `.env` file or
  `docker-compose.yaml` environment block.
- Verify the env var name matches what the provider expects (see the config
  keys table above).

### "Provider 'X' not found"

The orchestrator couldn't route to the named provider.

- Verify `svc-providers` is running and healthy.
- Check that the provider name in the agent definition matches a registered
  provider in `svc-providers`.
