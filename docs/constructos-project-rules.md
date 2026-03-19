# Project Rules

**Project Rules** are short, named guidelines attached to a project. They define how the team (and the AI agent) should work — the process agreements that aren't written down anywhere else.

---

## What rules are for

Rules are for the things everyone on the team knows but that new members (or an AI agent) wouldn't know by default:

- Your definition of done.
- How to handle status transitions.
- Naming conventions for tasks.
- What "blocked" means and who handles it.
- Standing technical preferences (e.g. "always write tests for new functions").

Every AI agent run for the project includes all project rules in its brief — so the agent follows the same standards without you having to repeat yourself each time.

---

## Creating a rule

**Project Settings → Rules → + New Rule**

Give the rule a short title (acts as a label) and write the body as a clear instruction.

### What makes a good rule

| Principle | Good | Avoid |
|---|---|---|
| **Short** | One instruction per rule | Multi-paragraph explanations |
| **Actionable** | "Do X when Y happens" | "Be thoughtful about…" |
| **Specific** | "Attach a screenshot as evidence when moving to Done" | "Document your work" |
| **Project-specific** | Only things that apply to *this* project | Generic best practices |

---

## Example rules

**Definition of done**
> A task is done when all acceptance criteria in the linked spec are verified, evidence is attached as a comment, and the task is moved to Done.

**Status transition protocol**
> When moving a task to a new status, leave a one-line comment explaining what changed and what the next step is.

**Task naming**
> All task titles use imperative verb form: "Add login page", "Fix checkout bug", "Write API docs".

**Handling blockers**
> If a task is blocked by an external dependency, add the label `blocked`, name the blocker in a comment, and assign an owner responsible for resolving it.

**Testing**
> Every new function must have at least one unit test. The agent should write the test alongside the implementation.

---

## Rules and the AI agent

When the AI agent picks up a task, it receives all project rules as part of its instructions. This means:

- A rule like "use TypeScript strict mode" is followed automatically.
- A rule like "always run the test suite before marking done" is respected.
- Updating a rule takes effect on the next agent run — no need to re-brief the agent.

> **Tip:** After a few agent runs, review the output. If the agent keeps doing something you need to correct, that correction probably belongs in a project rule.

---

*Next: [AI Automation →](constructos-ai-automation.md)*
