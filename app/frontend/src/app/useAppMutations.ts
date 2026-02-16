import { useNoteMutations } from './mutations/noteMutations'
import { useProjectMutations } from './mutations/projectMutations'
import { useTaskMutations } from './mutations/taskMutations'
import { useMiscMutations } from './mutations/miscMutations'

export function useAppMutations(c: any) {
  return {
    ...useTaskMutations(c),
    ...useProjectMutations(c),
    ...useNoteMutations(c),
    ...useMiscMutations(c),
  }
}
