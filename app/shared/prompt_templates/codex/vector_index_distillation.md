Distill the provided project text sources into compact retrieval-focused text for vector indexing.

Rules:
- Preserve only facts grounded in the source text.
- Prefer decisions, constraints, requirements, responsibilities, domain entities, and operational details.
- Remove filler, repetition, greetings, and generic prose.
- Do not invent missing details.
- Return one result for each input source.
- `distilled_text` must be plain text only.
- Keep each `distilled_text` concise but useful for semantic retrieval.

Input:
{payload_json}
