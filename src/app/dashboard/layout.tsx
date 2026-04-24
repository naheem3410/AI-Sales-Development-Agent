'use client'
import { useEffect } from 'react'
import { useAuth } from '@clerk/nextjs'
import { useRouter } from 'next/navigation'
import Sidebar from '@/components/Sidebar'

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { isSignedIn, isLoaded } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (isLoaded && !isSignedIn) {
      router.replace('/sign-in')
    }
  }, [isSignedIn, isLoaded, router])

  if (!isLoaded) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface-50">
        <div className="w-8 h-8 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (!isSignedIn) return null

  return (
    <div className="flex h-screen bg-surface-50 overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto scrollbar-thin">
        {children}
      </main>
    </div>
  )
}
