# Architecture

## Purpose

Content Manager is organized as a modular monolith. The backend owns content lifecycle, version history, generation, channel transformation, planning, and publication orchestration. External providers are adapters behind application-facing contracts.

## Layer boundaries

```text
HTTP / Telegram / Django
        |
        v
Transport adapters (routers, handlers, serializers)
        |
        v
Application services (use cases + transaction orchestration)
        |
        +------> Domain rules (state machines, invariants)
        |
        +------> Provider ports/adapters (AI, publication)
        |
        v
Persistence (SQLAlchemy models / PostgreSQL)
```

### Transport

Routers and handlers are responsible for HTTP/Telegram concerns: request validation, authentication dependencies, status-code mapping, and response serialization. They must not own lifecycle rules, provider orchestration, audit policy, or persistence workflows.

### Application services

Application services coordinate a complete use case and own the transaction-facing workflow. Current services include:

- `services/content_service.py` — content lookup, lifecycle transitions, workflow snapshots, and bulk transitions.
- `services/generation_service.py` — generation runs, immutable version creation, approval invalidation, and generation audit events.
- `services/variant_service.py` — channel validation, source-version selection, transformation, immutable variant history, and variant audit events.
- `services/publication_service.py` — publication claim/lease/execution orchestration.

Services may depend on domain rules, provider contracts, and persistence. They must not depend on FastAPI request/response types.

### Domain

The `domain/` package contains rules that do not require HTTP or infrastructure. The content state machine is the authoritative definition of valid lifecycle transitions. New business invariants belong here when they can be expressed without persistence or network concerns.

### Persistence

`models.py` and database/migration code are infrastructure. ORM entities represent persisted state and relationships; they are not the public application contract. Business decisions should be made before mutating ORM state and should be callable from non-HTTP entry points.

### Providers

AI generation, channel transformation, and publication integrations are provider ports/adapters. Provider failures are translated at the application boundary and must not leak provider SDK objects into transport or persistence code.

## Dependency rules

1. Transport may call application services.
2. Application services may call domain rules, persistence, and provider ports.
3. Domain code must not import FastAPI, SQLAlchemy sessions, provider SDKs, or transport modules.
4. Provider adapters must not import routers or application transport types.
5. ORM models must not contain workflow orchestration.
6. Cross-module use cases should be exposed as service functions/classes rather than duplicating logic in routers.

## Transaction rule

The current service boundary is intentionally explicit: application services mutate the SQLAlchemy session, while the transport layer commits or rolls back the request transaction. This keeps transaction ownership visible while removing business logic from HTTP handlers. Background workers should use the same services and own their transaction boundary explicitly.

## Module ownership

| Capability | Owner | Primary persistence |
|---|---|---|
| Content lifecycle | `content_service` + `domain/content_state_machine` | `contents` |
| Canonical history | content/version application flows | `content_versions` |
| AI generation | `generation_service` | `generation_runs`, `content_versions` |
| Channel variants | `variant_service` | `content_variants` |
| Planning/control plane | `content_service` | `contents`, `publications` |
| Publication execution | `publication_service` | `publications` |
| External providers | provider adapters | external systems |
| Audit | `audit.py` | audit/event tables |

## Architecture freeze criteria

Before adding substantial product features, new code should fit one of the existing capability modules. A new module requires a clear owner, public application contract, persistence ownership, and dependency direction. Avoid introducing a second path for the same business operation.
