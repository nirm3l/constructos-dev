import React from 'react'
import { parseCommaTags } from '../utils/ui'

export function useTagState(c: any) {
  const projectTagStats = React.useMemo(() => {
    const sourceStats = Array.isArray(c.projectTagsData?.tag_stats) ? c.projectTagsData.tag_stats : []
    const seen = new Set<string>()
    const out: Array<{ tag: string; usage_count: number }> = []
    for (const rawItem of sourceStats) {
      const tag = String(rawItem?.tag || '').trim()
      if (!tag) continue
      const key = tag.toLowerCase()
      if (seen.has(key)) continue
      seen.add(key)
      const usage = Number(rawItem?.usage_count)
      out.push({ tag, usage_count: Number.isFinite(usage) ? Math.max(0, usage) : 0 })
    }
    if (out.length > 0) return out

    const fallbackTags = Array.isArray(c.projectTagsData?.tags) ? c.projectTagsData.tags : []
    for (const rawTag of fallbackTags) {
      const tag = String(rawTag || '').trim()
      if (!tag) continue
      const key = tag.toLowerCase()
      if (seen.has(key)) continue
      seen.add(key)
      out.push({ tag, usage_count: 0 })
    }
    return out
  }, [c.projectTagsData?.tag_stats, c.projectTagsData?.tags])

  const tagUsageByName = React.useMemo(() => {
    const out: Record<string, number> = {}
    for (const item of projectTagStats) {
      out[item.tag.toLowerCase()] = item.usage_count
    }
    return out
  }, [projectTagStats])

  const getTagUsage = React.useCallback(
    (tag: string) => {
      const key = String(tag || '').trim().toLowerCase()
      if (!key) return 0
      return Number(tagUsageByName[key] ?? 0)
    },
    [tagUsageByName]
  )

  const buildSharedFilterTags = React.useCallback(() => {
    const seen = new Set<string>()
    const out: string[] = []
    for (const raw of [...(c.searchTags ?? []), ...(c.noteTags ?? []), ...(c.specificationTags ?? [])]) {
      const cleaned = String(raw || '').trim().toLowerCase()
      if (!cleaned || seen.has(cleaned)) continue
      seen.add(cleaned)
      out.push(cleaned)
    }
    return out
  }, [c.noteTags, c.searchTags, c.specificationTags])

  const applySharedFilterTagToggle = React.useCallback(
    (tag: string) => {
      const cleaned = String(tag || '').trim().toLowerCase()
      if (!cleaned) return
      const base = buildSharedFilterTags()
      const next = base.includes(cleaned) ? base.filter((t) => t !== cleaned) : [...base, cleaned]
      c.setSearchTags(next)
      c.setNoteTags(next)
      c.setSpecificationTags(next)
    },
    [buildSharedFilterTags, c.setNoteTags, c.setSearchTags, c.setSpecificationTags]
  )

  React.useEffect(() => {
    const merged = buildSharedFilterTags()
    const mergedKey = merged.join(',')
    if (
      String((c.searchTags ?? []).join(',')) === mergedKey &&
      String((c.noteTags ?? []).join(',')) === mergedKey &&
      String((c.specificationTags ?? []).join(',')) === mergedKey
    ) {
      return
    }
    c.setSearchTags(merged)
    c.setNoteTags(merged)
    c.setSpecificationTags(merged)
  }, [
    buildSharedFilterTags,
    c.noteTags,
    c.searchTags,
    c.setNoteTags,
    c.setSearchTags,
    c.setSpecificationTags,
    c.specificationTags,
  ])

  const taskTagSuggestions = React.useMemo(() => {
    return projectTagStats.map((item) => item.tag)
  }, [projectTagStats])

  const noteTagSuggestions = React.useMemo(() => {
    return projectTagStats.map((item) => item.tag)
  }, [projectTagStats])

  const toggleSearchTag = React.useCallback((tag: string) => {
    applySharedFilterTagToggle(tag)
  }, [applySharedFilterTagToggle])

  const toggleNoteFilterTag = React.useCallback((tag: string) => {
    applySharedFilterTagToggle(tag)
  }, [applySharedFilterTagToggle])

  const toggleSpecificationFilterTag = React.useCallback((tag: string) => {
    applySharedFilterTagToggle(tag)
  }, [applySharedFilterTagToggle])

  const clearSharedFilterTags = React.useCallback(() => {
    c.setSearchTags([])
    c.setNoteTags([])
    c.setSpecificationTags([])
  }, [c.setNoteTags, c.setSearchTags, c.setSpecificationTags])

  const clearSearchTags = React.useCallback(() => {
    clearSharedFilterTags()
  }, [clearSharedFilterTags])

  const clearNoteFilterTags = React.useCallback(() => {
    clearSharedFilterTags()
  }, [clearSharedFilterTags])

  const clearSpecificationFilterTags = React.useCallback(() => {
    clearSharedFilterTags()
  }, [clearSharedFilterTags])

  const addNoteTag = React.useCallback(
    (raw: string) => {
      const cleaned = String(raw || '').trim().replace(/,+$/, '')
      if (!cleaned) return
      const current = parseCommaTags(c.editNoteTags)
      const next = parseCommaTags([...current, cleaned].join(', '))
      c.setEditNoteTags(next.join(', '))
      c.setTagPickerQuery('')
    },
    [c.editNoteTags, c.setEditNoteTags, c.setTagPickerQuery]
  )

  const currentNoteTags = React.useMemo(() => parseCommaTags(c.editNoteTags), [c.editNoteTags])
  const currentNoteTagsLower = React.useMemo(() => new Set(currentNoteTags.map((t) => t.toLowerCase())), [currentNoteTags])

  const toggleNoteTag = React.useCallback(
    (tag: string) => {
      const cleaned = String(tag || '').trim()
      if (!cleaned) return
      const lower = cleaned.toLowerCase()
      const exists = currentNoteTagsLower.has(lower)
      const next = exists ? currentNoteTags.filter((t) => t.toLowerCase() !== lower) : [...currentNoteTags, cleaned]
      c.setEditNoteTags(parseCommaTags(next.join(', ')).join(', '))
    },
    [c.setEditNoteTags, currentNoteTags, currentNoteTagsLower]
  )

  const allNoteTags = React.useMemo(() => {
    const set = new Set<string>()
    const out: string[] = []
    for (const t of [...noteTagSuggestions, ...currentNoteTags]) {
      const cleaned = String(t || '').trim()
      if (!cleaned) continue
      const key = cleaned.toLowerCase()
      if (set.has(key)) continue
      set.add(key)
      out.push(cleaned)
    }
    return out
  }, [currentNoteTags, noteTagSuggestions])

  const filteredNoteTags = React.useMemo(() => {
    const q = c.tagPickerQuery.trim().toLowerCase()
    const base = q ? allNoteTags.filter((t) => t.toLowerCase().includes(q)) : allNoteTags
    return base.slice(0, 40)
  }, [allNoteTags, c.tagPickerQuery])

  const canCreateTag = React.useMemo(() => {
    const q = c.tagPickerQuery.trim()
    if (!q) return false
    return !allNoteTags.some((t) => t.toLowerCase() === q.toLowerCase())
  }, [allNoteTags, c.tagPickerQuery])

  const toggleTaskTag = React.useCallback(
    (tag: string) => {
      const cleaned = String(tag || '').trim()
      if (!cleaned) return
      const lower = cleaned.toLowerCase()
      const exists = c.editTaskTags.some((t: string) => t.toLowerCase() === lower)
      const next = exists ? c.editTaskTags.filter((t: string) => t.toLowerCase() !== lower) : [...c.editTaskTags, cleaned]
      c.setEditTaskTags(parseCommaTags(next.join(', ')))
    },
    [c.editTaskTags, c.setEditTaskTags]
  )

  const toggleQuickTaskTag = React.useCallback(
    (tag: string) => {
      const cleaned = String(tag || '').trim()
      if (!cleaned) return
      const lower = cleaned.toLowerCase()
      const exists = c.quickTaskTags.some((t: string) => t.toLowerCase() === lower)
      const next = exists ? c.quickTaskTags.filter((t: string) => t.toLowerCase() !== lower) : [...c.quickTaskTags, cleaned]
      c.setQuickTaskTags(parseCommaTags(next.join(', ')))
    },
    [c.quickTaskTags, c.setQuickTaskTags]
  )

  const filteredTaskTags = React.useMemo(() => {
    const q = c.taskTagPickerQuery.trim().toLowerCase()
    const base = q ? taskTagSuggestions.filter((t: string) => t.toLowerCase().includes(q)) : taskTagSuggestions
    return base.slice(0, 50)
  }, [c.taskTagPickerQuery, taskTagSuggestions])

  const taskTagsLower = React.useMemo(() => new Set(c.editTaskTags.map((t: string) => t.toLowerCase())), [c.editTaskTags])

  const canCreateTaskTag = React.useMemo(() => {
    const q = c.taskTagPickerQuery.trim()
    if (!q) return false
    return !taskTagSuggestions.some((t: string) => t.toLowerCase() === q.toLowerCase())
  }, [c.taskTagPickerQuery, taskTagSuggestions])

  const filteredQuickTaskTags = React.useMemo(() => {
    const q = c.quickTaskTagQuery.trim().toLowerCase()
    const base = q ? taskTagSuggestions.filter((t: string) => t.toLowerCase().includes(q)) : taskTagSuggestions
    return base.slice(0, 50)
  }, [c.quickTaskTagQuery, taskTagSuggestions])

  const quickTaskTagsLower = React.useMemo(() => new Set(c.quickTaskTags.map((t: string) => t.toLowerCase())), [c.quickTaskTags])

  const canCreateQuickTaskTag = React.useMemo(() => {
    const q = c.quickTaskTagQuery.trim()
    if (!q) return false
    return !taskTagSuggestions.some((t: string) => t.toLowerCase() === q.toLowerCase())
  }, [c.quickTaskTagQuery, taskTagSuggestions])

  return {
    taskTagSuggestions,
    noteTagSuggestions,
    getTagUsage,
    toggleSearchTag,
    toggleNoteFilterTag,
    toggleSpecificationFilterTag,
    clearSearchTags,
    clearNoteFilterTags,
    clearSpecificationFilterTags,
    addNoteTag,
    currentNoteTags,
    currentNoteTagsLower,
    toggleNoteTag,
    filteredNoteTags,
    canCreateTag,
    toggleTaskTag,
    toggleQuickTaskTag,
    filteredTaskTags,
    taskTagsLower,
    canCreateTaskTag,
    filteredQuickTaskTags,
    quickTaskTagsLower,
    canCreateQuickTaskTag,
  }
}
