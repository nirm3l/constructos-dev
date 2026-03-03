Classify chat instruction intent for task-management orchestration.

Input JSON:
{payload_json}

Return JSON only with fields:
- execution_intent: true when the user asks to start/continue/resume implementation or execution work on an existing project.
- execution_kickoff_intent: true only when the user asks to start/begin/kick off implementation and expects asynchronous team dispatch.
- project_creation_intent: true when the user asks to create/new/setup a project.
- reason: short rationale.

Rules:
- Do not infer from vague references; require clear intent in user wording.
- If instruction clearly asks to create project, set project_creation_intent=true and execution_kickoff_intent=false.
- execution_kickoff_intent implies execution_intent=true.
- If unsure, return all three booleans as false.
