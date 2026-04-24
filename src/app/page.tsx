import { auth } from '@clerk/nextjs/server'
import { redirect } from 'next/navigation'

/** Server-side redirect avoids a client-only spinner while Clerk hydrates. */
export default async function HomePage() {
  const { userId } = await auth()
  if (userId) redirect('/dashboard')
  redirect('/sign-in')
}
