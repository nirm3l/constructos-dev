# AI Automation

ConstructOS has a built-in AI agent that can execute tasks on your behalf. You write the brief, assign the task to the agent, and it does the work — logging every step inside the task so you have full visibility.

---

## How it works

```
You write a clear task  →  Assign to agent  →  Click Run now
                                                      ↓
                                               Agent reads:
                                               · Task description
                                               · Linked specification
                                               · Project rules
                                               · Related notes & context
                                                      ↓
                                              Agent executes
                                                      ↓
                                         Results logged in comments
                                         Task status updated
```

The full lifecycle in the task's automation status field:

| Status | What's happening |
|---|---|
| *(none)* | No automation running |
| **Queued** | Request submitted, waiting to start |
| **Running** | Agent is actively working |
| **Done** | Completed successfully — check comments for output |
| **Failed** | Something went wrong — reason is in the comments |

---

## Writing a brief the agent can act on

The quality of the output depends almost entirely on the quality of the brief. The agent can't ask clarifying questions — it works with what you give it.

### Good brief

> **Title:** Generate the March sprint summary report
>
> **Description:**
> Pull all tasks closed in March from this project. Group them by assignee. For each person, list the task titles and a one-line outcome. Write the summary as a markdown document and attach it as a comment on this task. Total time: all tasks combined. Tone: factual, no fluff.

### Too vague

> **Title:** Do the report

### Tips for better briefs

- **State the output explicitly.** "Write a markdown table" is clearer than "summarise things".
- **Link a specification.** The agent reads it as acceptance criteria. A clear spec is the best brief.
- **Add context in a linked note.** Background information, constraints, examples — put them in a note and link it to the task.
- **Use project rules for standing instructions.** If the agent should always do something (e.g. run tests, use a specific format), write it as a project rule so you don't have to repeat it.

---

## Reviewing agent output

When the agent finishes, open the task. The comments section contains:

- A summary of what was done.
- Any files created, code written, or commands run.
- The agent's assessment of whether acceptance criteria were met.

If it **failed**, the failure reason and partial work are in the comments. Fix the brief or spec and run again.

---

## In-app chat

The **Chat** panel is a separate, conversational interface to the same AI — scoped to your project.

Use it for:
- **Quick questions:** "What tasks are blocked right now?" or "Summarise the Discovery notes."
- **Creating tasks:** "Create a task to add email validation to the signup form" — the agent creates it immediately.
- **Finding context:** "What did we decide about the authentication approach?"

Chat searches your project's notes and specs to answer questions. It only sees content from the current project.

> **Chat vs. automation:** Chat is conversational and instant. Automation (assigning a task to the agent) is asynchronous and produces traceable output inside the task. Use chat for exploration, use automation for execution.

---

## Context: what the agent sees

Before triggering a large automated task, open **Project → Context**. This shows the full context pack the agent receives:

- Task details.
- Linked spec.
- Project rules.
- Related notes and dependency tasks.

If something important is missing from this view, add it (as a note, spec, or rule) before running. The agent can only work with what's in the context pack.

---

*Next: [Tips & Best Practices →](constructos-tips.md)*
