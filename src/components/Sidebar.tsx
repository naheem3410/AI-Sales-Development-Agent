'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useUser, UserButton } from '@clerk/nextjs'
import { config } from '@/config'
import { cn } from '@/lib/utils'
import {
  LayoutDashboard,
  Megaphone,
  BookOpen,
  Send,
  Zap,
  CreditCard,
} from 'lucide-react'

const NAV = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/campaigns', label: 'Campaigns', icon: Megaphone },
  { href: '/billing', label: 'Plan & billing', icon: CreditCard },
  { href: '/knowledge', label: 'Knowledge', icon: BookOpen },
  { href: '/settings/outreach', label: 'Sending', icon: Send },
]

export default function Sidebar() {
  const pathname  = usePathname()
  const { user }  = useUser()

  return (
    <aside className="w-[220px] flex-shrink-0 flex flex-col border-r border-surface-200 bg-white">
      {/* Logo */}
      <div className="h-16 flex items-center px-5 border-b border-surface-200">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 bg-brand-600 rounded-lg flex items-center justify-center">
            <Zap size={13} className="text-white" fill="white" />
          </div>
          <span className="font-semibold text-ink text-sm">{config.app.name}</span>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 p-3 space-y-0.5">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active =
            href === '/dashboard'
              ? pathname === '/dashboard'
              : href === '/billing'
                ? pathname.startsWith('/billing')
              : href === '/settings/outreach'
                ? pathname.startsWith('/settings')
                : pathname.startsWith(href)
          return (
            <Link
              key={href}
              href={href}
              className={cn('nav-item', active && 'nav-item-active')}
            >
              <Icon size={16} />
              {label}
            </Link>
          )
        })}
      </nav>

      {/* User footer */}
      <div className="p-3 border-t border-surface-200">
        <div className="flex items-center gap-3 px-2 py-2 rounded-xl hover:bg-surface-50 transition-colors">
          <UserButton afterSignOutUrl="/sign-in" />
          <div className="min-w-0">
            <p className="text-xs font-medium text-ink truncate">
              {user?.fullName || user?.primaryEmailAddress?.emailAddress || 'Account'}
            </p>
            <p className="text-[11px] text-ink-subtle truncate">
              {user?.primaryEmailAddress?.emailAddress}
            </p>
          </div>
        </div>
      </div>
    </aside>
  )
}
