# Amplifier CLI Gaps Analysis: Current IPC CLI vs Original App CLI

## Executive Summary

The current Amplifier IPC CLI (`amplifier-ipc-cli`) is a **minimal HTTP client** for the Amplifier IPC microservices architecture, while the original CLI (`amplifier-app-cli`) is a **comprehensive, feature-rich application**. There are significant gaps across all major functional areas.

**Key Metrics:**
- **Current IPC CLI:** ~1,295 lines of code, 8 modules
- **Original App CLI:** ~11,108 lines in commands alone, 70+ modules, 19 command groups

**Architecture Difference:**
- **Current:** HTTP client → session-service → microservices
- **Original:** Direct kernel integration with rich local capabilities

---

## Feature Gap Analysis by Category

### 🔴 **CRITICAL GAPS - Core CLI Commands**

| Feature | Original CLI | Current IPC CLI | Gap Severity |
|---------|--------------|-----------------|--------------|
| **Bundle Management** | Full `bundle` command group (1,226 LOC) | ❌ None | 🔴 Critical |
| **Provider Management** | Full `provider` command group (1,230 LOC) | ❌ None | 🔴 Critical |
| **Module Management** | Full `module` command group (935 LOC) | ❌ None | 🔴 Critical |
| **Session Management** | Rich `session` commands (1,457 LOC) | ❌ Basic slash commands only | 🔴 Critical |
| **Tool Invocation** | `tool invoke` with full inspection (500 LOC) | ❌ None | 🔴 Critical |
| **Source Management** | `source` command group (537 LOC) | ❌ None | 🔴 Critical |
| **Update System** | `update` command (1,112 LOC) | ❌ None | 🔴 Critical |
| **Reset System** | `reset` with interactive mode (790 LOC) | ❌ None | 🔴 Critical |

### 🟡 **MAJOR GAPS - Session & Configuration**

| Feature | Original CLI | Current IPC CLI | Gap Severity |
|---------|--------------|-----------------|--------------|
| **Interactive Session Features** | Rich REPL with 12+ slash commands | Basic REPL with 7 slash commands | 🟡 Major |
| **Session History & Resume** | Full session store, fork, lineage | ❌ No persistence | 🟡 Major |
| **Configuration Management** | Multi-scope settings, inheritance | Basic settings only | 🟡 Major |
| **Bundle Integration** | Native bundle loading & validation | ❌ None | 🟡 Major |
| **Runtime Mentions** | `@file` loading with deduplication | Basic `@file` mention processing | 🟡 Major |
| **Error Display** | Rich error formatting, LLM error handling | Basic error display | 🟡 Major |

### 🟠 **MODERATE GAPS - User Experience**

| Feature | Original CLI | Current IPC CLI | Gap Severity |
|---------|--------------|-----------------|--------------|
| **Agent Management** | `agents` command group | ❌ None | 🟠 Moderate |
| **Directory Permissions** | `allowed-dirs`, `denied-dirs` commands | ❌ None | 🟠 Moderate |
| **Notification System** | `notify` command group | ❌ None | 🟠 Moderate |
| **Routing Management** | `routing` command group (1,479 LOC) | ❌ None | 🟠 Moderate |
| **Shell Completion** | Auto-detection and installation | ❌ None | 🟠 Moderate |
| **First-run Setup** | Interactive `init` with provider config | ❌ None | 🟠 Moderate |

### 🟢 **MINOR GAPS - Polish & Convenience**

| Feature | Original CLI | Current IPC CLI | Gap Severity |
|---------|--------------|-----------------|--------------|
| **Output Formats** | text, json, json-trace | text, json | 🟢 Minor |
| **Verbose Logging** | Comprehensive verbose mode | Basic verbose mode | 🟢 Minor |
| **Help System** | Rich help with formatting | Standard click help | 🟢 Minor |
| **Version Display** | Core + app version info | Basic version only | 🟢 Minor |

---

## Detailed Command Comparison

### Original CLI Command Structure (19 groups)
```
amplifier
├── run                    # Execution engine
├── bundle                 # Bundle management (43K LOC)
├── provider               # Provider management (43K LOC)
├── module                 # Module management (31K LOC)
├── session                # Session management (51K LOC)
├── tool                   # Tool invocation (16K LOC)
├── source                 # Source management (16K LOC)
├── agents                 # Agent management (3K LOC)
├── allowed-dirs           # Directory permissions (5K LOC)
├── denied-dirs            # Directory permissions (6K LOC)
├── routing                # Request routing (51K LOC)
├── notify                 # Notifications (14K LOC)
├── update                 # Self-update system (40K LOC)
├── reset                  # Reset/cleanup (17K LOC)
├── init                   # First-run setup (16K LOC)
├── version                # Version info (1K LOC)
└── (completion)           # Shell completion
```

### Current IPC CLI Structure (2 commands + REPL)
```
amplifier-svc
├── run                    # HTTP client to session-service
├── version                # Basic version info
└── (internal REPL)        # HTTP streaming REPL
```

---

## Critical Missing Infrastructure

### 1. **Bundle System** (🔴 Critical)
The original CLI has comprehensive bundle management:
- Bundle discovery, loading, validation
- Multi-scope bundle configuration (user, project, session)
- Bundle addition, removal, activation
- Bundle source management
- Bundle status and health checking

**Current IPC CLI:** No bundle concept - relies entirely on service-side configuration.

### 2. **Provider Ecosystem** (🔴 Critical)
The original CLI provides:
- Provider installation and management
- Provider configuration and authentication
- Model listing and selection
- Provider priority and routing
- Provider source management

**Current IPC CLI:** No provider management - providers must be configured at service level.

### 3. **Module Lifecycle** (🔴 Critical)
The original CLI handles:
- Module discovery and installation
- Module validation and health checking
- Module updates and version management
- Module source configuration
- Module caching and cleanup

**Current IPC CLI:** No module concept - all modules managed at service level.

### 4. **Session Persistence** (🔴 Critical)
The original CLI provides:
- Session storage and metadata
- Session resume and continuation
- Session forking and lineage tracking
- Session naming and organization
- Session search and discovery

**Current IPC CLI:** Sessions are stateless HTTP interactions.

---

## Architecture Implications

### Current IPC CLI Constraints
1. **Service Dependency:** Requires running session-service + microservices
2. **Limited Offline Capability:** Cannot function without service infrastructure
3. **Configuration Gap:** No local configuration management
4. **State Gap:** No local state persistence
5. **Extensibility Gap:** Cannot extend functionality without service changes

### Original CLI Capabilities
1. **Self-Contained:** Works with kernel + modules directly
2. **Offline Operation:** Full functionality without external services
3. **Rich Configuration:** Multi-layered configuration system
4. **Persistent State:** Local session and configuration storage
5. **Extensible:** Plugin architecture via modules and bundles

---

## Migration Considerations

### Immediate Priorities (P0)
1. **Basic Configuration Management** - Settings, providers, modules
2. **Session Persistence** - Resume capability, history
3. **Bundle Integration** - Local bundle loading
4. **Error Handling** - Rich error display

### Secondary Priorities (P1)
1. **Module Management** - Install, update, validate modules
2. **Provider Management** - Configure, authenticate, manage providers
3. **Tool Invocation** - Direct tool access
4. **Shell Integration** - Completion, first-run setup

### Long-term Considerations (P2)
1. **Advanced Session Features** - Forking, lineage, metadata
2. **Notification System** - Status updates, alerts
3. **Directory Permissions** - Security controls
4. **Update System** - Self-updating capability

---

## Recommendations

### Option 1: Enhanced IPC CLI
Extend the current IPC CLI to bridge the gap:
- Add configuration management layer
- Implement local session storage
- Provide bundle loading capabilities
- Add provider/module management commands

**Pros:** Leverages microservices architecture
**Cons:** Dual complexity (client + service configuration)

### Option 2: Hybrid Approach
Maintain both CLIs for different use cases:
- IPC CLI for service-oriented deployments
- Original CLI for direct/local development
- Unified configuration format

**Pros:** Best of both worlds
**Cons:** Maintenance burden, user confusion

### Option 3: Service Enhancement
Focus on making the service layer handle more CLI responsibilities:
- Move bundle management to session-service
- Add configuration endpoints
- Implement session persistence in service
- Enhanced HTTP API for all management operations

**Pros:** Consistent architecture, single source of truth
**Cons:** Service becomes heavy, reduces local capability

---

## Conclusion

The current IPC CLI is fundamentally a **different product** than the original CLI. It's an HTTP client optimized for microservices interaction, while the original is a comprehensive development tool.

**Biggest Risks:**
1. **User Workflow Disruption** - Users lose 95% of CLI functionality
2. **Development Friction** - No local configuration/module management
3. **Service Dependency** - Cannot work offline or in simple environments

**Path Forward:**
Consider Option 1 (Enhanced IPC CLI) with gradual feature parity restoration, starting with P0 items (configuration, sessions, bundles, errors).