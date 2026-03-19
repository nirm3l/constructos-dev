# Notes

**Notes** are long-lived documents that live alongside your work. They're for the things that matter to your project but don't fit into a task or spec — decisions, context, meeting outcomes, research, checklists.

Unlike task comments (which belong to a single task), notes are project-wide, searchable, and can be organised, linked, and pinned.

---

## Creating a note

Go to **Notes** in the project sidebar → **+ New Note**.

Write in markdown. Everything you can do in a spec — headings, tables, code blocks, checklists — works in notes too.

---

## Note groups

Organise notes into **colour-coded groups** that reflect how your team works. Some common patterns:

| Group | What goes here |
|---|---|
| **Discovery** | Research, user interviews, product decisions, brainstorms |
| **Shiproom** | Release checklists, deployment records, post-mortems |
| **Meetings** | Standups, retrospectives, planning sessions |
| **Architecture** | Design decisions, ADRs, diagrams |
| **Reference** | Glossary, team conventions, onboarding guides |

Create groups from the Notes sidebar. You can colour-code them and reorder them at any time.

---

## Pinning notes

**Pin** a note to keep it permanently at the top of the list, regardless of when it was last updated.

Good candidates for pinning:
- Team onboarding guide.
- Current sprint goals or focus areas.
- Active incident status.
- "How we work" conventions.

---

## Linking notes

Connect notes to other parts of your project:

- **Link to a task** → the note appears in that task's related notes panel.
- **Link to a spec** → groups implementation context and decisions around the spec.

A single note can be linked to both a task and a spec simultaneously.

---

## Tags

Add **tags** to notes for cross-group filtering. Click a tag anywhere in the notes list to filter to all notes with that tag. Useful when topics cut across groups (e.g. all notes tagged `authentication`, regardless of which group they're in).

---

## Archiving notes

Archive a note when it's no longer actively relevant but you don't want to delete it.

- Archived notes disappear from the main list.
- They're always recoverable from the archive view.
- Use archiving for completed sprint notes, old decisions, or superseded docs.

---

## What goes where

This is the most common source of confusion for new teams:

| Content type | The right place |
|---|---|
| Work that needs to be done | **Task** |
| What "done" means for a feature | **Specification** |
| Decision made and why | **Note** |
| Context the team needs to reference | **Note** |
| Short standing process guideline | **Project Rule** |
| Running log while implementing a task | **Note** linked to the task |
| Post-release observation or incident record | **Note** in a Shiproom group |
| Question about a task | **Task comment** |

---

> **Pattern:** For any non-trivial task, create a note alongside it titled "Implementation journal — [task name]". Update it as you work. Link it to the task. When you hand off or the task closes, you have a complete record of what happened and why.

---

*Next: [Project Rules →](constructos-project-rules.md)*
