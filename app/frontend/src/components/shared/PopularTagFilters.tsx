import React from 'react'
import { Icon } from './uiHelpers'

const DEFAULT_VISIBLE_TAGS = 10

type PopularTagFiltersProps = {
  tags: string[]
  selectedTags: string[]
  onToggleTag: (tag: string) => void
  onClear: () => void
  getTagUsage: (tag: string) => number
  idPrefix: string
  visibleCount?: number
}

export function PopularTagFilters({
  tags,
  selectedTags,
  onToggleTag,
  onClear,
  getTagUsage,
  idPrefix,
  visibleCount = DEFAULT_VISIBLE_TAGS,
}: PopularTagFiltersProps) {
  const [showAll, setShowAll] = React.useState(false)

  React.useEffect(() => {
    setShowAll(false)
  }, [tags])

  const maxVisible = Math.max(1, visibleCount)
  const visibleTags = showAll ? tags : tags.slice(0, maxVisible)
  const remainingCount = Math.max(0, tags.length - visibleTags.length)
  const canExpand = tags.length > maxVisible

  return (
    <>
      {visibleTags.map((tag) => {
        const usageCount = getTagUsage(tag)
        return (
          <button
            key={`${idPrefix}-${tag}`}
            className={`status-chip tag-filter-chip ${selectedTags.includes(tag.toLowerCase()) ? 'active' : ''}`}
            onClick={() => onToggleTag(tag)}
            aria-pressed={selectedTags.includes(tag.toLowerCase())}
            title={usageCount > 0 ? `Used in ${usageCount} items` : 'Tag'}
          >
            <span>#{tag}</span>
            {usageCount > 0 && <span className="tag-filter-count">{usageCount}</span>}
          </button>
        )
      })}

      {!showAll && remainingCount > 0 && (
        <button
          className="status-chip tag-filter-more"
          type="button"
          onClick={() => setShowAll(true)}
          aria-label={`Show ${remainingCount} more tags`}
        >
          +{remainingCount} more
        </button>
      )}

      {showAll && canExpand && (
        <button
          className="status-chip tag-filter-more"
          type="button"
          onClick={() => setShowAll(false)}
          aria-label="Show fewer tags"
        >
          Show less
        </button>
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
    </>
  )
}
