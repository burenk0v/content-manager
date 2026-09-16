# Architecture

## Purpose

Content Manager is a modular monolith. The backend owns content lifecycle, version history, generation, channel transformation, planning, and publication orchestration. External providers are adapters behind application-facing contracts.

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

Routers and handlers own request validation, authentication dependencies, status-code mapping, and response serialization. They must not own lifecycle rules, provider orchestration, audit policy, or persistence workflows.

### Application services

Application services coordinate complete use cases and the transaction-facing workflow. Current services include `content_service.py`, `generation_service.py`, `variant_service.py`, and `publication_service.py`.

Services may depend on domain rules, provider contracts, and persistence. They must not depend on FastAPI request/response types.

### Domain

The `domain/` package contains rules that do not require HTTP or infrastructure. The content state machine is the authoritative definition of valid lifecycle transitions.

### Persistence

ORM models and migration code are infrastructure. ORM entities represent durable state; they are not the public application contract. Business decisions should be made before mutating ORM state and should be callable from non-HTTP entry points.

### Providers

AI generation, channel transformation, and publication integrations are provider ports/adapters. Provider failures are translated at the application boundary and provider SDK objects must not leak into transport or persistence code.

## Dependency rules

1. Transport may call application services.
2. Application services may call domain rules, persistence, and provider ports.
3. Domain code must not import FastAPI, Starlette, SQLAlchemy, provider SDKs, or transport modules.
4. Provider adapters must not import routers or application transport types.
5. ORM models must not contain workflow orchestration.
6. Cross-module use cases should be exposed as service functions/classes rather than duplicated in routers.

The domain dependency rule is executable in `backend/scripts/check_architecture.py` and is a CI gate.

## Transaction rule

Application services mutate the SQLAlchemy session, while the transport layer commits or rolls back the request transaction. Background workers own their transaction boundary explicitly while reusing the same application services.

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

## Repository topology

The active backend runtime is rooted at `backend/src/app`. The repository also contains `backend/app`, which holds isolated application/provider worker contracts from the execution-model work. It is not a second HTTP application entry point and must not become one without an explicit architectural decision.

## Architecture freeze

The architecture is frozen for normal product development. New feature work should extend an existing capability owner first. A new module, persistence mechanism, provider contract, or cross-layer dependency requires an explicit owner, public contract, dependency direction, and ADR.

Refactoring remains allowed when driven by a concrete product requirement, measured operational problem, or documented architectural decision. Silent architectural drift and duplicate implementation paths are not allowed.

See `docs/ADR/0005-architecture-freeze.md` for the decision record.
