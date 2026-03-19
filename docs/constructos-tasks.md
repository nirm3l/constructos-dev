# Tasks

Tasks are the core unit of work in ConstructOS. They live on a board, move through your custom statuses, and can be assigned to a person or the AI agent.

---

## Creating a task

Use the **+ FAB button** (bottom-right corner) or click **+** at the top of any board column.

| Field | What to put here |
|---|---|
| **Title** | Short imperative label: "Add login page", "Fix checkout bug" |
| **Description** | Markdown body — context, links, acceptance notes |
| **Status** | Which column it starts in |
| **Priority** | Low / Med / High / Critical |
| **Due date** | Optional deadline |
| **Assignee** | A team member, or the AI agent |
| **Labels** | Free-form tags: `bug`, `blocked`, `frontend`, `quick-win` |
| **Task group** | Which sprint or milestone this belongs to |
| **Specification** | Link to the spec that defines done for this task |

---

## Board view

The board organises tasks as cards across status columns.

- **Drag and drop** a card to a new column to change its status.
- **Click a card** to open the full task detail.
- **Filter bar** (top) lets you narrow by assignee, label, priority, or due date.
- **Collapse a column** when you want to focus on fewer statuses.

> **Tip:** Keep your board honest. A task sitting in "In Progress" for two weeks isn't in progress — move it to a blocked or waiting state so the board reflects reality.

---

## List view

The list shows all tasks in a sortable table. Switch to it when you want to:
- Review a large backlog without scrolling through cards.
- Sort by due date or priority across all statuses.
- Do quick inline edits on multiple tasks.

---

## Task groups

Group tasks into **sprints, milestones, or epics** using task groups. Create them from the board sidebar.

Task groups can be:
- **Collapsed** to hide completed work.
- **Colour-coded** to visually distinguish different phases.
- **Reordered** to reflect your current sprint order.

---

## Task relationships

Link tasks together to model dependencies:

| Relationship | Meaning |
|---|---|
| **Depends on** | This task can't start until the linked task is done |
| **Blocks** | Completing this task unblocks the linked task |

Relationships are shown in the task detail panel and are included in the AI agent's context — so the agent knows what work precedes and follows the task it's running.

---

## Subtasks

Add a **subtask checklist** inside the task description or via the subtasks panel. Each item can be checked off independently. The task card shows a progress indicator (e.g. `3 / 5`).

---

## Comments and activity

Every task has a comment thread and an automatic activity log.

Good uses for comments:
- **Mid-execution:** "Decided to scope out the mobile breakpoints — adding a separate task."
- **Handoff:** "Moved to QA — test with user account `demo@example.com`, password `test123`."
- **Evidence:** "Verified all acceptance criteria. Screenshot attached."

Comments from the AI agent also appear here — it logs what it did and why.

---

## Recurring tasks

Set a **recurring rule** to have a task recreated automatically on a schedule (daily, weekly, or custom cron). Useful for:
- Weekly team check-ins.
- Monthly report generation.
- Regular maintenance tasks.

When a recurring task is completed, the next instance is created automatically based on the schedule.

---

## Saved views

Save any filter configuration as a **named view** for instant access. Good examples:

- *My open tasks* — filtered to you, all statuses except Done.
- *Blocked items* — filtered by `blocked` label.
- *Due this week* — filtered by due date range.
- *Agent tasks* — filtered by `agent` label or AI assignee.

---

*Next: [Specifications →](constructos-specifications.md)*
