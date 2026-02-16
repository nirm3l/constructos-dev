import { useNoteMutations } from './mutations/noteMutations'
import { useProjectMutations } from './mutations/projectMutations'
import { useSpecificationMutations } from './mutations/specificationMutations'
import { useTaskMutations } from './mutations/taskMutations'
import { useMiscMutations } from './mutations/miscMutations'

export function useAppMutations(c: any) {
  return {
    ...useTaskMutations(c),
    ...useProjectMutations(c),
    ...useNoteMutations(c),
    ...useSpecificationMutations(c),
    ...useMiscMutations(c),
  }
}
