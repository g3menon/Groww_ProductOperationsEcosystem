/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  // Allow build to succeed even with TypeScript errors
  typescript: {
    ignoreBuildErrors: true,
  },

  // Allow build to succeed even with ESLint errors
  eslint: {
    ignoreDuringBuilds: true,
  },
};

export default nextConfig; // PROD: force redeploy
