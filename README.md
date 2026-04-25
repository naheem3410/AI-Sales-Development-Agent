# SDA Platform — Frontend

Next.js 14 frontend for the SDA (Sales Development Agent) platform.

## Stack

- **Next.js 14** — App Router, static export for S3/CloudFront
- **Clerk** — Authentication (client-side, compatible with static export)
- **Tailwind CSS** — Styling with custom design tokens
- **Sonner** — Toast notifications
- **Recharts** — Analytics charts
- **TypeScript** — Fully typed API client and components

---

## Setup

### 1. Install dependencies

```bash
npm install
```

### 2. Configure environment

```bash
cp .env.local.example .env.local
```

Edit `.env.local` with your values:

| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Clerk publishable key from your Clerk dashboard |
| `CLERK_SECRET_KEY` | Clerk secret key (server-side, not exposed to client) |
| `NEXT_PUBLIC_API_BASE_URL` | Your SDA backend URL, e.g. `http://localhost:8000` |
| `NEXT_PUBLIC_PIPELINE_POLL_INTERVAL` | Pipeline status polling interval in ms (default: `5000`) |
| `NEXT_PUBLIC_ONBOARDING_POLL_INTERVAL` | Onboarding polling interval in ms (default: `3000`) |
| `NEXT_PUBLIC_LEADS_PAGE_SIZE` | Leads per page in the leads table (default: `25`) |

### 3. Run locally

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

---

## Configurable values

All configurable runtime values are centralised in `src/config/index.ts`. You can override any of these via environment variables — no code changes needed.

---

## Production build (S3 + CloudFront)

```bash
npm run build
```

This produces a static export in `out/`. Upload the contents to your S3 bucket.

### CloudFront configuration required

Because this is a client-side SPA, CloudFront must redirect 404/403 errors to `index.html`:

1. In your CloudFront distribution, go to **Error Pages**
2. Add a custom error response:
   - HTTP error code: `403` and `404`
   - Response page path: `/index.html`
   - HTTP response code: `200`

This ensures deep links (e.g. `/campaigns/abc123`) work correctly.

---

## Project structure

```
src/
├── app/
│   ├── layout.tsx              # Root layout (ClerkProvider, fonts, Toaster)
│   ├── globals.css             # Design tokens, base styles
│   ├── page.tsx                # Root redirect (→ /dashboard or /sign-in)
│   ├── sign-in/page.tsx        # Clerk sign-in
│   ├── sign-up/page.tsx        # Clerk sign-up
│   ├── dashboard/
│   │   ├── layout.tsx          # Auth guard + sidebar
│   │   └── page.tsx            # Dashboard home
│   └── campaigns/
│       ├── layout.tsx          # Auth guard + sidebar
│       ├── page.tsx            # Campaigns list
│       ├── new/page.tsx        # New campaign form
│       └── [campaignId]/
│           ├── page.tsx        # Campaign detail (tabs)
│           ├── ICPTab.tsx      # ICP view + edit
│           ├── BriefTab.tsx    # Product brief view + edit
│           ├── LeadsTab.tsx    # Leads table with filtering
│           ├── EmailsTab.tsx   # Email sequences list
│           ├── leads/[leadId]/page.tsx     # Lead detail
│           └── emails/[leadId]/page.tsx    # Email sequence editor
├── components/
│   ├── Sidebar.tsx             # Navigation sidebar
│   └── ui.tsx                  # Shared UI primitives
├── config/
│   └── index.ts                # All configurable values
├── hooks/
│   ├── useApiClient.ts         # Clerk token → API client
│   └── usePolling.ts           # Generic polling hook
├── lib/
│   ├── api.ts                  # Typed API client
│   └── utils.ts                # Helpers (cn, formatters, color maps)
└── types/
    └── api.ts                  # TypeScript types from OpenAPI schema
```

---

## Auth notes

Clerk auth is handled entirely client-side (required for static export). There is no middleware file — route protection is done via `useAuth()` in layout components. This is the standard approach for Clerk + Next.js static exports deployed to S3/CloudFront.

---

## API client

The typed API client lives in `src/lib/api.ts`. Every endpoint from the OpenAPI spec is covered. Usage:

```ts
const { getClient } = useApiClient()
const client = await getClient() // fetches fresh Clerk token
const campaigns = await client.listCampaigns()
```
