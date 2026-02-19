from __future__ import annotations

from dataclasses import dataclass, field


DDD_PRODUCT_BUILD_KEY = "ddd_product_build"
MOBILE_BROWSER_GAME_KEY = "mobile_browser_game_development"


@dataclass(frozen=True, slots=True)
class TemplateSpecification:
    title: str
    body: str = ""
    status: str = "Ready"


@dataclass(frozen=True, slots=True)
class TemplateTask:
    title: str
    description: str = ""
    priority: str = "Med"
    labels: tuple[str, ...] = ()
    specification_title: str | None = None


@dataclass(frozen=True, slots=True)
class TemplateRule:
    title: str
    body: str = ""


@dataclass(frozen=True, slots=True)
class TemplateGraphNode:
    node_key: str
    label: str
    title: str
    props: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TemplateGraphEdge:
    source_node_key: str
    source_label: str
    relation: str
    target_node_key: str
    target_label: str


@dataclass(frozen=True, slots=True)
class ProjectTemplateDefinition:
    key: str
    name: str
    version: str
    description: str
    default_custom_statuses: tuple[str, ...]
    default_embedding_enabled: bool
    default_context_pack_evidence_top_k: int | None
    specifications: tuple[TemplateSpecification, ...]
    tasks: tuple[TemplateTask, ...]
    rules: tuple[TemplateRule, ...]
    graph_nodes: tuple[TemplateGraphNode, ...] = ()
    graph_edges: tuple[TemplateGraphEdge, ...] = ()


_DDD_TEMPLATE = ProjectTemplateDefinition(
    key=DDD_PRODUCT_BUILD_KEY,
    name="DDD Product Build",
    version="1.0.0",
    description=(
        "Template for event-driven product development using bounded contexts, "
        "aggregates, commands, events, and projection-oriented delivery."
    ),
    default_custom_statuses=("To do", "In progress", "Review", "Done"),
    default_embedding_enabled=True,
    default_context_pack_evidence_top_k=14,
    specifications=(
        TemplateSpecification(
            title="Bounded Context and Ubiquitous Language",
            body=(
                "Define bounded contexts, context map, ownership boundaries, and "
                "a shared ubiquitous language glossary for core terms."
            ),
        ),
        TemplateSpecification(
            title="Aggregate Contracts and Invariants",
            body=(
                "Design aggregate roots, entities, value objects, and write-side "
                "invariant rules with failure modes."
            ),
        ),
        TemplateSpecification(
            title="Command and Domain Event Catalog",
            body=(
                "Define command contracts, event payload schemas, versioning rules, "
                "and compatibility constraints."
            ),
        ),
        TemplateSpecification(
            title="Projection and Read Model Design",
            body=(
                "Specify read models, projection lag tolerances, and reporting "
                "queries used by UI and automation workers."
            ),
        ),
        TemplateSpecification(
            title="Integration Boundaries and ACL",
            body=(
                "Document external integration contracts, anti-corruption layers, "
                "and translation rules at boundaries."
            ),
        ),
    ),
    tasks=(
        TemplateTask(
            title="Create context map and glossary draft",
            description="Produce first-pass context map and shared language document.",
            priority="High",
            labels=("ddd", "discovery"),
            specification_title="Bounded Context and Ubiquitous Language",
        ),
        TemplateTask(
            title="Review aggregate invariants with domain stakeholders",
            description="Validate business invariants and reject invalid transitions.",
            priority="High",
            labels=("ddd", "aggregate"),
            specification_title="Aggregate Contracts and Invariants",
        ),
        TemplateTask(
            title="Define command payload contracts",
            description="Write command schemas with validation and expected errors.",
            priority="High",
            labels=("ddd", "commands"),
            specification_title="Command and Domain Event Catalog",
        ),
        TemplateTask(
            title="Define domain event schemas and upcasting strategy",
            description="Capture event evolution strategy and upcaster constraints.",
            priority="High",
            labels=("ddd", "events", "schema"),
            specification_title="Command and Domain Event Catalog",
        ),
        TemplateTask(
            title="Design SQL read models and projection checkpoints",
            description="Specify read-side tables and checkpointing behavior.",
            priority="Med",
            labels=("projection", "read-model"),
            specification_title="Projection and Read Model Design",
        ),
        TemplateTask(
            title="Document external integration ACL contracts",
            description="Define ACL translation contracts for external systems.",
            priority="Med",
            labels=("integration", "acl"),
            specification_title="Integration Boundaries and ACL",
        ),
    ),
    rules=(
        TemplateRule(
            title="All write-side changes must flow through commands and events",
            body="No direct state mutation without explicit command and emitted domain event.",
        ),
        TemplateRule(
            title="Aggregate invariants are enforced inside aggregate boundaries",
            body="Validation rules must not be spread across unrelated modules.",
        ),
        TemplateRule(
            title="Every domain event must have an owning aggregate and consumer map",
            body="Event producers and projection consumers must be traceable.",
        ),
    ),
    graph_nodes=(
        TemplateGraphNode(node_key="bc_core", label="BoundedContext", title="Core Context"),
        TemplateGraphNode(node_key="agg_product", label="Aggregate", title="Product Aggregate"),
        TemplateGraphNode(node_key="cmd_create_product", label="Command", title="CreateProduct"),
        TemplateGraphNode(node_key="cmd_update_product", label="Command", title="UpdateProduct"),
        TemplateGraphNode(node_key="evt_product_created", label="DomainEvent", title="ProductCreated"),
        TemplateGraphNode(node_key="evt_product_updated", label="DomainEvent", title="ProductUpdated"),
        TemplateGraphNode(node_key="rm_product_overview", label="ReadModel", title="ProductOverview"),
        TemplateGraphNode(node_key="policy_unique_name", label="Policy", title="EnforceUniqueProductName"),
        TemplateGraphNode(node_key="boundary_catalog_acl", label="IntegrationBoundary", title="CatalogACLBoundary"),
    ),
    graph_edges=(
        TemplateGraphEdge(
            source_node_key="bc_core",
            source_label="BoundedContext",
            relation="CONTAINS_AGGREGATE",
            target_node_key="agg_product",
            target_label="Aggregate",
        ),
        TemplateGraphEdge(
            source_node_key="agg_product",
            source_label="Aggregate",
            relation="HANDLES_COMMAND",
            target_node_key="cmd_create_product",
            target_label="Command",
        ),
        TemplateGraphEdge(
            source_node_key="agg_product",
            source_label="Aggregate",
            relation="HANDLES_COMMAND",
            target_node_key="cmd_update_product",
            target_label="Command",
        ),
        TemplateGraphEdge(
            source_node_key="agg_product",
            source_label="Aggregate",
            relation="EMITS_EVENT",
            target_node_key="evt_product_created",
            target_label="DomainEvent",
        ),
        TemplateGraphEdge(
            source_node_key="agg_product",
            source_label="Aggregate",
            relation="EMITS_EVENT",
            target_node_key="evt_product_updated",
            target_label="DomainEvent",
        ),
        TemplateGraphEdge(
            source_node_key="evt_product_created",
            source_label="DomainEvent",
            relation="UPDATES_READ_MODEL",
            target_node_key="rm_product_overview",
            target_label="ReadModel",
        ),
        TemplateGraphEdge(
            source_node_key="evt_product_updated",
            source_label="DomainEvent",
            relation="UPDATES_READ_MODEL",
            target_node_key="rm_product_overview",
            target_label="ReadModel",
        ),
        TemplateGraphEdge(
            source_node_key="policy_unique_name",
            source_label="Policy",
            relation="ENFORCES_POLICY",
            target_node_key="agg_product",
            target_label="Aggregate",
        ),
        TemplateGraphEdge(
            source_node_key="boundary_catalog_acl",
            source_label="IntegrationBoundary",
            relation="CROSSES_BOUNDARY",
            target_node_key="bc_core",
            target_label="BoundedContext",
        ),
    ),
)


_MOBILE_BROWSER_GAME_TEMPLATE = ProjectTemplateDefinition(
    key=MOBILE_BROWSER_GAME_KEY,
    name="Mobile Browser Game Development",
    version="1.0.0",
    description=(
        "Template for building and shipping touch-first browser games optimized "
        "for mobile devices, with performance guardrails and repeatable release flow."
    ),
    default_custom_statuses=("Backlog", "In progress", "QA on devices", "Ready to deploy", "Done"),
    default_embedding_enabled=True,
    default_context_pack_evidence_top_k=15,
    specifications=(
        TemplateSpecification(
            title="Core Gameplay Loop and Controls",
            body=(
                "Define core gameplay loop, touch controls, fail/win states, and "
                "session length targets for mobile players."
            ),
        ),
        TemplateSpecification(
            title="Rendering and Asset Pipeline",
            body=(
                "Document sprite/audio pipeline, compression strategy, cache policy, "
                "and runtime loading model for mobile browsers."
            ),
        ),
        TemplateSpecification(
            title="Performance Budget and Device Matrix",
            body=(
                "Define FPS, memory, bundle-size budgets and target device/browser "
                "matrix with acceptance thresholds."
            ),
        ),
        TemplateSpecification(
            title="Progress Persistence and Resilience",
            body=(
                "Specify local/session persistence strategy, reconnect behavior, and "
                "graceful degradation for constrained networks."
            ),
        ),
        TemplateSpecification(
            title="Release and LAN Deployment Pipeline",
            body=(
                "Define reproducible Docker Compose release pipeline, health checks, "
                "and local-network access for QA playtests."
            ),
        ),
    ),
    tasks=(
        TemplateTask(
            title="Prototype touch input and movement loop",
            description="Implement first playable loop with gesture/touch controls.",
            priority="High",
            labels=("mobile-game", "controls"),
            specification_title="Core Gameplay Loop and Controls",
        ),
        TemplateTask(
            title="Build sprite atlas and lazy-loading asset manifest",
            description="Set up compressed textures and non-blocking asset loading.",
            priority="High",
            labels=("mobile-game", "assets"),
            specification_title="Rendering and Asset Pipeline",
        ),
        TemplateTask(
            title="Establish FPS and memory benchmarks for target devices",
            description="Create repeatable benchmark scenario across baseline devices.",
            priority="High",
            labels=("mobile-game", "performance"),
            specification_title="Performance Budget and Device Matrix",
        ),
        TemplateTask(
            title="Implement save-state fallback and recovery flow",
            description="Persist progress with robust fallback for network interruptions.",
            priority="High",
            labels=("mobile-game", "resilience"),
            specification_title="Progress Persistence and Resilience",
        ),
        TemplateTask(
            title="Create Docker Compose deployment profile for LAN QA",
            description="Expose game container on a LAN-accessible port for device testing.",
            priority="High",
            labels=("mobile-game", "deploy", "docker"),
            specification_title="Release and LAN Deployment Pipeline",
        ),
        TemplateTask(
            title="Wire gameplay telemetry events for retention analysis",
            description="Track session start/end, retry, and completion funnel events.",
            priority="Med",
            labels=("mobile-game", "telemetry"),
            specification_title="Performance Budget and Device Matrix",
        ),
    ),
    rules=(
        TemplateRule(
            title="All releases must be deployed through Docker Compose on a LAN-accessible port",
            body=(
                "Every release candidate must start via docker compose and bind to 0.0.0.0 "
                "on the agreed QA port so test devices on local network can open the game."
            ),
        ),
        TemplateRule(
            title="Gameplay frame budget is mandatory before feature sign-off",
            body="Features are blocked from Done if FPS and memory budgets fail on baseline devices.",
        ),
        TemplateRule(
            title="Asset payload growth must stay within agreed mobile limits",
            body="Bundle and texture growth requires explicit review when crossing performance thresholds.",
        ),
    ),
    graph_nodes=(
        TemplateGraphNode(node_key="loop_core", label="GameplayLoop", title="Core Gameplay Loop"),
        TemplateGraphNode(node_key="input_touch", label="InputScheme", title="Touch Input Scheme"),
        TemplateGraphNode(node_key="assets_pipeline", label="AssetPipeline", title="Asset Pipeline"),
        TemplateGraphNode(node_key="device_baseline", label="DeviceProfile", title="Baseline Device Profile"),
        TemplateGraphNode(node_key="budget_perf", label="PerformanceBudget", title="Performance Budget"),
        TemplateGraphNode(node_key="deploy_lan", label="DeploymentTarget", title="LAN QA Deployment Target"),
        TemplateGraphNode(node_key="release_pipeline", label="ReleasePipeline", title="Compose Release Pipeline"),
        TemplateGraphNode(node_key="metric_retention", label="TelemetryMetric", title="Session Retention Metric"),
    ),
    graph_edges=(
        TemplateGraphEdge(
            source_node_key="loop_core",
            source_label="GameplayLoop",
            relation="DEFINES_INPUT_SCHEME",
            target_node_key="input_touch",
            target_label="InputScheme",
        ),
        TemplateGraphEdge(
            source_node_key="loop_core",
            source_label="GameplayLoop",
            relation="BUILDS_ASSETS",
            target_node_key="assets_pipeline",
            target_label="AssetPipeline",
        ),
        TemplateGraphEdge(
            source_node_key="budget_perf",
            source_label="PerformanceBudget",
            relation="TARGETS_DEVICE_PROFILE",
            target_node_key="device_baseline",
            target_label="DeviceProfile",
        ),
        TemplateGraphEdge(
            source_node_key="release_pipeline",
            source_label="ReleasePipeline",
            relation="DEPLOYS_TO",
            target_node_key="deploy_lan",
            target_label="DeploymentTarget",
        ),
        TemplateGraphEdge(
            source_node_key="release_pipeline",
            source_label="ReleasePipeline",
            relation="ENFORCES_BUDGET",
            target_node_key="budget_perf",
            target_label="PerformanceBudget",
        ),
        TemplateGraphEdge(
            source_node_key="loop_core",
            source_label="GameplayLoop",
            relation="TRACKS_METRIC",
            target_node_key="metric_retention",
            target_label="TelemetryMetric",
        ),
    ),
)


_TEMPLATES: dict[str, ProjectTemplateDefinition] = {
    _DDD_TEMPLATE.key: _DDD_TEMPLATE,
    _MOBILE_BROWSER_GAME_TEMPLATE.key: _MOBILE_BROWSER_GAME_TEMPLATE,
}

_ALIASES: dict[str, str] = {
    DDD_PRODUCT_BUILD_KEY: DDD_PRODUCT_BUILD_KEY,
    "ddd": DDD_PRODUCT_BUILD_KEY,
    "ddd-product-build": DDD_PRODUCT_BUILD_KEY,
    MOBILE_BROWSER_GAME_KEY: MOBILE_BROWSER_GAME_KEY,
    "mobile-browser-game-development": MOBILE_BROWSER_GAME_KEY,
    "mobile-browser-game": MOBILE_BROWSER_GAME_KEY,
    "mobile_browser_game": MOBILE_BROWSER_GAME_KEY,
    "mobile-game": MOBILE_BROWSER_GAME_KEY,
    "browser-game": MOBILE_BROWSER_GAME_KEY,
}


def normalize_template_key(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in _ALIASES:
        return _ALIASES[raw]
    return raw.replace("-", "_").replace(" ", "_")


def list_template_definitions() -> list[ProjectTemplateDefinition]:
    return sorted(_TEMPLATES.values(), key=lambda item: item.name.casefold())


def get_template_definition(template_key: str) -> ProjectTemplateDefinition | None:
    normalized = normalize_template_key(template_key)
    canonical = _ALIASES.get(normalized, normalized)
    return _TEMPLATES.get(canonical)
