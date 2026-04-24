/** @type {import('next').NextConfig} */
const isStaticExport = process.env.NEXT_STATIC_EXPORT === 'true'

const nextConfig = {
  // Amplify needs 'standalone' for SSR/Middleware (Clerk) to work.
  // We only use 'export' if explicitly requested for S3/CloudFront.
  ...(isStaticExport ? {
    output: 'export',
    trailingSlash: true,
  } : {
    output: 'standalone',
  }),

  images: {
    unoptimized: true,
  },

  // This block ensures the server-side runtime (Amplify) 
  // can "see" these variables from the environment.
  env: {
    NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
    NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY,
    CLERK_SECRET_KEY: process.env.CLERK_SECRET_KEY,
  },
}

module.exports = nextConfig