Classify the provided project artifact for event storming.

Return JSON matching the schema exactly.

Scope definitions:
- `product_domain`: The artifact is primarily about the product/system domain, behavior, domain entities, rules, aggregates, commands, events, read models, or bounded contexts specific to the project being built.
- `delivery_process`: The artifact is primarily about implementation workflow, QA handoff, release readiness, deployment, orchestration, evidence collection, oversight, blockers, or ConstructOS/team process.
- `mixed`: The artifact contains both project-domain content and delivery-process content.
- `unknown`: The artifact is too vague, generic, or ambiguous to classify safely.

Decision policy:
- Be conservative. If explicit project-domain content is weak or missing, prefer `delivery_process` or `unknown`.
- Do not treat generic process terms as product-domain concepts.
- For `mixed`, keep only the domain-specific parts in `domain_text`.
- For `product_domain`, `domain_text` may be the original meaning compressed into a shorter domain-focused summary.
- For `delivery_process` and `unknown`, return an empty `domain_text`.
- `domain_text` must stay fully grounded in the source text. No invention.
- Keep `domain_text` plain text only.

Input:
{payload_json}
