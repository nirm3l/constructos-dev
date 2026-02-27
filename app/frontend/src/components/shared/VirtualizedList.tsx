import React from 'react'
import { useVirtualizer, useWindowVirtualizer } from '@tanstack/react-virtual'

type VirtualizedListProps<T> = {
  items: T[]
  estimateSize: number
  overscan?: number
  maxHeight?: number | string
  className?: string
  scrollMode?: 'window' | 'container'
  itemKey?: (item: T, index: number) => string | number
  renderItem: (item: T, index: number) => React.ReactNode
}

export function VirtualizedList<T>({
  items,
  estimateSize,
  overscan = 8,
  maxHeight = '72vh',
  className = '',
  scrollMode = 'window',
  itemKey,
  renderItem,
}: VirtualizedListProps<T>) {
  const scrollRef = React.useRef<HTMLDivElement | null>(null)
  const getRowKey = React.useCallback((index: number) => {
    const item = items[index]
    if (!itemKey || item === undefined) return index
    return itemKey(item, index)
  }, [itemKey, items])

  const containerVirtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => estimateSize,
    overscan,
    getItemKey: getRowKey,
    enabled: scrollMode === 'container',
  })

  const windowVirtualizer = useWindowVirtualizer({
    count: items.length,
    estimateSize: () => estimateSize,
    overscan,
    getItemKey: getRowKey,
    enabled: scrollMode === 'window',
  })

  const virtualizer = scrollMode === 'window' ? windowVirtualizer : containerVirtualizer

  if (scrollMode === 'window') {
    return (
      <div className={`virtualized-list-window ${className}`.trim()}>
        <div
          style={{
            height: `${virtualizer.getTotalSize()}px`,
            width: '100%',
            position: 'relative',
          }}
        >
          {virtualizer.getVirtualItems().map((virtualRow) => {
            const item = items[virtualRow.index]
            if (item === undefined) return null
            return (
              <div
                key={virtualRow.key}
                data-index={virtualRow.index}
                ref={virtualizer.measureElement}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  transform: `translateY(${virtualRow.start}px)`,
                }}
              >
                {renderItem(item, virtualRow.index)}
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  return (
    <div
      ref={scrollRef}
      className={`virtualized-list-scroll ${className}`.trim()}
      style={{ maxHeight }}
    >
      <div
        style={{
          height: `${virtualizer.getTotalSize()}px`,
          width: '100%',
          position: 'relative',
        }}
      >
        {virtualizer.getVirtualItems().map((virtualRow) => {
          const item = items[virtualRow.index]
          if (item === undefined) return null
          return (
            <div
              key={virtualRow.key}
              data-index={virtualRow.index}
              ref={virtualizer.measureElement}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                transform: `translateY(${virtualRow.start}px)`,
              }}
            >
              {renderItem(item, virtualRow.index)}
            </div>
          )
        })}
      </div>
    </div>
  )
}
