Classify chat instruction intent for task-management orchestration.

Input JSON:
{payload_json}

Return JSON only with fields:
- execution_intent: true when the user asks to start/continue/resume implementation or execution work on an existing project.
- execution_kickoff_intent: true only when the user asks to start/begin/kick off implementation and expects asynchronous team dispatch.
- project_creation_intent: true when the user asks to create/new/setup a project.
- project_knowledge_lookup_intent: true when the user asks a factual question whose answer should be looked up from project artifacts such as tasks, notes, specifications, rules, or indexed attachments.
- grounded_answer_required: true when the assistant should answer only from retrieved project evidence and should say it cannot verify the answer if evidence is missing.
- workflow_scope: one of `team_mode`, `single_agent`, `unknown`.
- execution_mode: one of `setup_only`, `setup_then_kickoff`, `kickoff_only`, `resume_execution`, `unknown`.
- deploy_requested: true when the user explicitly wants deployment execution as part of this request.
- docker_compose_requested: true when the user explicitly asks for Docker Compose setup/deploy.
- requested_port: integer port when explicitly requested, else null.
- code_review_required: true only when the user explicitly asks to require code review before merge, else false.
- project_name_provided: true when the request explicitly names the project to create/setup, else false.
- task_completion_requested: true when the request explicitly asks to complete/mark the task done, else false.
- reason: short rationale.

Rules:
- Do not infer from vague references; require clear intent in user wording.
- This classifier is the authoritative path for ambiguous setup/execution/kickoff recognition; downstream runtime code must not replace it with string heuristics.
- Classification must be language-agnostic: equivalent requests in different languages should yield equivalent outputs.
- If instruction clearly asks to create/setup a project, set project_creation_intent=true.
- If the same instruction also explicitly asks to start/kick off execution after setup, set execution_kickoff_intent=true as well.
- If the instruction explicitly asks to require code review before merge, set code_review_required=true. Otherwise set it to false.
- If instruction asks only for setup/creation (without explicit start/kickoff), set execution_kickoff_intent=false.
- If instruction asks to create/setup a project but does not actually provide the project name, set project_name_provided=false.
- If the instruction explicitly asks to complete the current task, set task_completion_requested=true.
- If the instruction asks for a concrete project fact, value, setting, identifier, decision, port, URL, owner, date, or other artifact-backed answer, set project_knowledge_lookup_intent=true.
- If the instruction is a factual lookup and hallucinating would be risky, set grounded_answer_required=true.
- grounded_answer_required should usually be true when project_knowledge_lookup_intent=true.
- execution_kickoff_intent implies execution_intent=true.
- Prefer one consistent interpretation over keyword matching. Use the full request meaning.
- If unsure, return safe-negative/unknown outputs:
  - booleans false,
  - workflow_scope=`unknown`,
  - execution_mode=`unknown`,
  - requested_port=null,
  - code_review_required=false,
  - project_name_provided=false,
  - task_completion_requested=false.
