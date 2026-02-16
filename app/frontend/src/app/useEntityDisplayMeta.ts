import { pickSingleTimeMeta } from '../utils/ui'

export function useEntityDisplayMeta(args: {
  actorNames: Record<string, string>
  selectedTask: any
  selectedNote: any
  selectedProject: any
}) {
  const { actorNames, selectedTask, selectedNote, selectedProject } = args

  const selectedTaskTimeMeta = pickSingleTimeMeta(selectedTask?.created_at, selectedTask?.updated_at)
  const selectedNoteTimeMeta = pickSingleTimeMeta(selectedNote?.created_at, selectedNote?.updated_at)
  const selectedProjectTimeMeta = pickSingleTimeMeta(selectedProject?.created_at, selectedProject?.updated_at)
  const selectedTaskCreator = selectedTask?.created_by ? actorNames[selectedTask.created_by] || selectedTask.created_by : 'Unknown'
  const selectedNoteCreator = selectedNote?.created_by ? actorNames[selectedNote.created_by] || selectedNote.created_by : 'Unknown'
  const selectedProjectCreator = selectedProject?.created_by ? actorNames[selectedProject.created_by] || selectedProject.created_by : 'Unknown'

  return {
    selectedTaskTimeMeta,
    selectedNoteTimeMeta,
    selectedProjectTimeMeta,
    selectedTaskCreator,
    selectedNoteCreator,
    selectedProjectCreator,
  }
}
