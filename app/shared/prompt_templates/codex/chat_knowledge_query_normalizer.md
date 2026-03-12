Normalize a project-knowledge retrieval query for multilingual semantic lookup.

Input JSON:
{payload_json}

Return JSON only with fields:
- project_knowledge_lookup_intent: whether the message is asking for a factual answer that should be retrieved from project artifacts.
- grounded_answer_required: whether the answer should be grounded in retrieved project evidence.
- input_language: short language tag such as `en`, `bs`, `hr`, `sr`, `de`, `es`, or `unknown`.
- english_retrieval_query: a short English query optimized for retrieving the answer from project artifacts.
- native_retrieval_query: a short query in the user's input language when useful; otherwise an empty string is allowed.
- reasoning: short rationale.

Rules:
- Preserve meaning, not wording.
- Treat multilingual and indirect phrasing the same as direct English factual lookup when the user is asking for a concrete value, fact, setting, number, name, port, status, or policy that could exist in project notes, tasks, specifications, rules, or chat attachments.
- Set `project_knowledge_lookup_intent=true` for those factual project questions, regardless of language.
- Set `grounded_answer_required=true` when the question asks for a concrete fact that should be verified from project artifacts.
- Focus on the core factual thing being asked for.
- Remove politeness, filler, and indirect phrasing.
- Prefer compact noun phrases or short factual lookup queries over full sentences.
- If the input is already English, `english_retrieval_query` may closely match the original meaning.
- If the input is non-English, translate the retrieval meaning into concise English.
- `native_retrieval_query` should be the concise query in the source language when that would help retrieval.
- Do not answer the question. Only normalize the retrieval query.
- If the message is not a factual project lookup, return:
  - `project_knowledge_lookup_intent=false`
  - `grounded_answer_required=false`
  - empty retrieval queries if appropriate

Examples:
- Input: "what is the secret number?"
  Output intent:
  - project_knowledge_lookup_intent=`true`
  - grounded_answer_required=`true`
  - input_language=`en`
  - english_retrieval_query=`secret number`
  - native_retrieval_query=`secret number`

- Input: "mozes li mi reci koji je tajni broj?"
  Output intent:
  - project_knowledge_lookup_intent=`true`
  - grounded_answer_required=`true`
  - input_language=`bs`
  - english_retrieval_query=`secret number`
  - native_retrieval_query=`tajni broj`

- Input: "welcher port wird verwendet?"
  Output intent:
  - project_knowledge_lookup_intent=`true`
  - grounded_answer_required=`true`
  - input_language=`de`
  - english_retrieval_query=`port used`
  - native_retrieval_query=`verwendeter port`
