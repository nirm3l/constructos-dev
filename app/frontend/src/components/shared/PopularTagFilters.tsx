import React from 'react'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import * as ToggleGroup from '@radix-ui/react-toggle-group'
import { Icon } from './uiHelpers'

const DEFAULT_VISIBLE_TAGS = 10

type PopularTagFiltersProps = {
  tags: string[]
  selectedTags: string[]
  onToggleTag: (tag: string) => void
  onClear: () => void
  idPrefix: string
  visibleCount?: number
}

export function PopularTagFilters({
  tags,
  selectedTags,
  onToggleTag,
  onClear,
  idPrefix,
  visibleCount = DEFAULT_VISIBLE_TAGS,
}: PopularTagFiltersProps) {
  const [overflowQuery, setOverflowQuery] = React.useState('')
  const maxVisible = Math.max(1, visibleCount)
  const visibleTags = tags.slice(0, maxVisible)
  const overflowTags = tags.slice(maxVisible)
  const filteredOverflowTags = React.useMemo(() => {
    const query = overflowQuery.trim().toLowerCase()
    if (!query) return overflowTags
    return overflowTags.filter((tag) => tag.toLowerCase().includes(query))
  }, [overflowQuery, overflowTags])
  const selectedSet = React.useMemo(() => new Set(selectedTags.map((tag) => tag.toLowerCase())), [selectedTags])
  const visibleValues = React.useMemo(
    () => visibleTags.filter((tag) => selectedSet.has(tag.toLowerCase())).map((tag) => tag.toLowerCase()),
    [selectedSet, visibleTags]
  )

  const handleVisibleTagValuesChange = React.useCallback((nextValues: string[]) => {
    const nextSet = new Set(nextValues)
    for (const tag of visibleTags) {
      const normalizedTag = tag.toLowerCase()
      const wasSelected = selectedSet.has(normalizedTag)
      const willBeSelected = nextSet.has(normalizedTag)
      if (wasSelected !== willBeSelected) onToggleTag(tag)
    }
  }, [onToggleTag, selectedSet, visibleTags])

  return (
    <>
      <ToggleGroup.Root
        className="tag-filter-toggle-group"
        type="multiple"
        value={visibleValues}
        onValueChange={handleVisibleTagValuesChange}
        aria-label="Popular tags"
      >
        {visibleTags.map((tag) => (
          <ToggleGroup.Item
            key={`${idPrefix}-${tag}`}
            className="status-chip tag-filter-chip"
            value={tag.toLowerCase()}
            aria-label={`Filter by tag ${tag}`}
            title={`#${tag}`}
          >
            <span>#{tag}</span>
          </ToggleGroup.Item>
        ))}
        {overflowTags.length > 0 && (
          <DropdownMenu.Root onOpenChange={(open) => { if (!open) setOverflowQuery('') }}>
            <DropdownMenu.Trigger asChild>
              <button
                className="status-chip tag-filter-more"
                type="button"
                aria-label={`Show ${overflowTags.length} more tags`}
                title="More tags"
              >
                +{overflowTags.length}
              </button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content className="task-group-menu-content tag-filter-menu-content" sideOffset={8} align="start">
                <div className="tag-filter-menu-search">
                  <input
                    value={overflowQuery}
                    onChange={(event) => setOverflowQuery(event.target.value)}
                    onKeyDown={(event) => event.stopPropagation()}
                    placeholder="Filter tags"
                    aria-label="Filter additional tags"
                  />
                </div>
                <DropdownMenu.Separator className="task-group-menu-separator" />
                {filteredOverflowTags.map((tag) => (
                  <DropdownMenu.CheckboxItem
                    key={`${idPrefix}-overflow-${tag}`}
                    className="task-group-menu-item tag-filter-menu-item"
                    checked={selectedSet.has(tag.toLowerCase())}
                  onCheckedChange={() => onToggleTag(tag)}
                >
                  <span className="tag-filter-menu-label">#{tag}</span>
                  <DropdownMenu.ItemIndicator className="tag-filter-menu-item-indicator">
                    <Icon path="M5 13l4 4L19 7" />
                  </DropdownMenu.ItemIndicator>
                  </DropdownMenu.CheckboxItem>
                ))}
                {filteredOverflowTags.length === 0 && (
                  <div className="tag-filter-menu-empty">No matching tags.</div>
                )}
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
        )}

        {selectedTags.length > 0 && (
          <button
            className="action-icon tag-filter-clear"
            type="button"
            onClick={onClear}
            title="Clear selected tags"
            aria-label="Clear selected tags"
          >
            <Icon path="M6 6l12 12M18 6 6 18" />
          </button>
        )}
      </ToggleGroup.Root>
    </>
  )
}
