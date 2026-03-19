# Tips & Best Practices

Practical advice for getting the most out of ConstructOS, based on patterns that work well in practice.

---

## Before you add a single task

Set up the scaffolding first. Ten minutes here saves hours of reorganisation later.

1. **Define your statuses.** These become your board columns. Fewer is better — only add a column if it genuinely represents a distinct stage in your workflow.
2. **Write 2–3 project rules.** At minimum: a definition of done and a note on how to handle blockers.
3. **Create task groups** for your sprints or milestones. Tasks with a home are easier to prioritise.

---

## Write the spec before you start the task

For anything that takes more than a day or involves more than one person, write the spec first.

This feels like extra work. It isn't. It forces clarity before effort is invested, and it pays off in three ways:
- The person doing the work has an unambiguous brief.
- The AI agent can execute without guessing.
- You have a permanent record of what was decided and why.

---

## Keep your board honest

A task that's been "In Progress" for two weeks isn't in progress. Common fixes:

| Situation | What to do |
|---|---|
| Blocked externally | Add label `blocked`, comment with blocker + owner |
| Waiting for review | Move to a "Review" or "Waiting" status |
| Scope crept | Split into two tasks |
| Abandoned | Move to Backlog or archive |

The board should reflect reality at a glance. If it doesn't, filtering and planning become unreliable.

---

## Task titles are your first filter

You'll scan task titles hundreds of times. Make them worth reading.

**Imperative, specific:**
- `Add email validation to the signup form`
- `Fix null pointer on the invoice export page`
- `Write onboarding sequence for new trial users`

**Vague, useless for scanning:**
- `Email stuff`
- `Bug fix`
- `Content`

The same titles end up in the AI agent's context. The agent executes "Add email validation to the signup form" reliably. It guesses at "Email stuff".

---

## Use labels to cut across the board

Labels let you filter across all statuses and groups at once. A few high-value conventions:

| Label | Use it for |
|---|---|
| `blocked` | Waiting on something outside the team |
| `bug` | Production defects |
| `quick-win` | Under 1 hour — useful for filling gaps between larger tasks |
| `agent` | Tasks designated for AI execution |
| `needs-spec` | Work that needs a spec before it can be started |

---

## Comment when you move a task

One line is enough:

> "Moved to Review — all acceptance criteria verified, screenshot attached."

> "Moved back to In Progress — QA found an edge case with empty cart checkout."

This creates a timeline inside every task. When something goes wrong, or when you need to onboard someone new, the history is right there.

---

## Use notes as a running implementation journal

Don't wait until a task is done to document what happened. Create a note alongside any significant task, titled something like *"Sprint 3 / auth refactor — working notes"*, and add bullet points as you go:

- Decision made and why.
- Scope that was added or cut.
- Risks noticed and mitigations chosen.
- Links to external references (PRs, designs, meeting notes).

Link the note to the task. When you close the task, the journal stays in the project — searchable, linkable, permanent.

---

## Let the agent handle repetitive work

Recurring tasks are ideal for automation:

- Weekly sprint summaries.
- Monthly metrics reports.
- Regular dependency audits.
- Scheduled changelog updates.

Set up a recurring task, assign it to the agent, write a clear description of the expected output. Review the result each time — you stay in the loop, the agent does the execution.

---

## Check context before a big agent run

Open **Project → Context** before triggering any complex automated task. This shows the exact brief the agent will receive. If key information is missing — an important decision, a constraint, a linked spec that isn't there yet — add it before running.

A five-minute context review often saves a full retry cycle.

---

## One more thing: use the Demo project

The Demo project exists to be explored and broken. If you want to test how something works — automation, delivery checks, board views — do it there first before setting it up in a project your team is actively using.
