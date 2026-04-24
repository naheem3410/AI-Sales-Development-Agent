'use client'
import { useState, useEffect, useRef, useCallback } from 'react'
import { config } from '@/config'

interface PollingOptions<T> {
  fetcher: () => Promise<T>
  shouldStop: (data: T) => boolean
  interval?: number
  enabled?: boolean
  onError?: (err: unknown) => void
}

export function usePolling<T>({
  fetcher,
  shouldStop,
  interval = config.polling.pipelineInterval,
  enabled = true,
  onError,
}: PollingOptions<T>) {
  const [data, setData]       = useState<T | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState<Error | null>(null)
  const [stopped, setStopped] = useState(false)

  const retries      = useRef(0)
  const timerRef     = useRef<ReturnType<typeof setTimeout> | null>(null)
  const fetcherRef   = useRef(fetcher)
  const shouldStopRef = useRef(shouldStop)

  fetcherRef.current   = fetcher
  shouldStopRef.current = shouldStop

  const stop = useCallback(() => {
    setStopped(true)
    if (timerRef.current) clearTimeout(timerRef.current)
  }, [])

  // When polling is (re-)enabled, allow ticks again — otherwise a previous run
  // left stopped=true and the campaign page would never poll after e.g. Run Pipeline.
  useEffect(() => {
    if (enabled) {
      setStopped(false)
      retries.current = 0
    }
  }, [enabled])

  useEffect(() => {
    if (!enabled || stopped) return

    let cancelled = false

    const tick = async () => {
      if (cancelled) return
      try {
        setLoading(true)
        const result = await fetcherRef.current()
        if (cancelled) return
        setData(result)
        setError(null)
        retries.current = 0

        if (shouldStopRef.current(result)) {
          setStopped(true)
          return
        }
      } catch (err) {
        if (cancelled) return
        setError(err as Error)
        onError?.(err)
        retries.current++
        if (retries.current >= config.polling.maxRetries) {
          setStopped(true)
          return
        }
      } finally {
        if (!cancelled) setLoading(false)
      }

      timerRef.current = setTimeout(tick, interval)
    }

    tick()

    return () => {
      cancelled = true
      if (timerRef.current) clearTimeout(timerRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, stopped, interval])

  return { data, loading, error, stopped, stop }
}
