# Welcome to ConstructOS

ConstructOS is a project and task management platform with a built-in AI agent. Your team plans work, tracks progress, and ships — and the AI agent can pick up tasks and execute them on your behalf, inside the same tool.

---

## What you can do

| Capability | How it helps |
|---|---|
| **Projects** | Organise work into focused spaces, each with its own board, notes, and specs. |
| **Tasks** | Track every piece of work. Move cards across custom board columns as work progresses. |
| **Specifications** | Write acceptance criteria once. Link them to tasks so everyone knows what "done" means. |
| **Notes** | Keep decisions, research, and context in one place — searchable and linked to your work. |
| **Project Rules** | Short guidelines that govern how the team (and the AI agent) works in a project. |
| **AI Automation** | Assign a task to the AI agent. It reads the brief, does the work, and reports back. |
| **Chat** | Ask the AI assistant questions about your project, or describe a task and let it create it. |

---

## How everything connects

```
Project
 ├── Tasks  ──────────────── linked to ──→  Specification
 │    ├── Subtasks                            (acceptance criteria)
 │    ├── Comments & activity log
 │    └── AI agent run
 │
 ├── Notes  ──────────────── linked to ──→  Task or Specification
 │    └── Note groups (Discovery, Shiproom…)
 │
 ├── Specifications
 │    └── Status: Draft → Ready → Archived
 │
 └── Project Rules  ─────── injected into every AI agent run
```

---

## Navigating the UI

| Panel | Where to find it |
|---|---|
| **Board** | Tasks → Board view. Drag cards across status columns. |
| **List** | Tasks → List view. Sortable table, good for bulk review. |
| **Specifications** | Left sidebar → Specs icon. |
| **Notes** | Left sidebar → Notes icon. |
| **Chat** | Bottom bar → Chat icon. |
| **Context** | Project menu → Context. Shows what the AI sees before it runs. |
| **Delivery Checks** | Project menu → Delivery Checks. Checkpoints before a task can close. |
| **Settings** | Project menu → Settings. Statuses, rules, members, integrations. |

---

## Getting started in 5 steps

1. Open the **Demo** project — it has example tasks, notes, and a spec so you can see how everything fits together.
2. **Create a new project** from the sidebar. Pick a starter template or start blank.
3. **Set your board statuses** in Project Settings (e.g. `To Do → In Progress → Review → Done`).
4. **Add a few tasks** and move them across the board.
5. **Write a specification**, link it to a task, then assign that task to the AI agent and run it.

---

> **Tip:** The Demo project is always a safe sandbox — nothing you do there affects other projects. Use it to experiment before setting up your real workspace.

---

*Next: [Projects →](constructos-projects.md)*
