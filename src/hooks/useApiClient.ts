'use client'
import { useAuth } from '@clerk/nextjs'
import { useCallback } from 'react'
import { createApiClient } from '@/lib/api'

// Returns a stable api client bound to the current Clerk token
export function useApiClient() {
  const { getToken } = useAuth()

  const getClient = useCallback(async () => {
    const token = await getToken()
    if (!token) throw new Error('Not authenticated')
    return createApiClient(token)
  }, [getToken])

  return { getClient }
}
