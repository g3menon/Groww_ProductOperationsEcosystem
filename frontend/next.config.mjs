/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  // TypeScript errors always fail the build (default is false / no override needed,
  // but being explicit prevents accidental overrides in CI forks).
  typescript: {
    ignoreBuildErrors: false,
  },

  // ESLint errors always fail the build.
  eslint: {
    ignoreDuringBuilds: false,
  },
};

export default nextConfig;  // PROD: force redeploy
