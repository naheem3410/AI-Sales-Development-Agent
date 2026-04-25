'use client'
import { useAuth } from '@clerk/nextjs'
import { useCallback } from 'react'
import { createApiClient } from '@/lib/api'

// Returns a stable api client bound to the current Clerk token
export function useApiClient() {
  const { getToken } = useAuth()

  // Pass getToken (not a one-shot string) so api.ts can `skipCache: true` and retry once on 401.
  const getClient = useCallback(async () => {
    return createApiClient(getToken)
  }, [getToken])

  return { getClient }
}
