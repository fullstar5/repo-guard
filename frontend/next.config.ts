import type { NextConfig } from "next";

const apiOrigin = (process.env.API_ORIGIN ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        // Browser calls /api/auth/me; FastAPI serves /auth/me.
        source: "/api/:path*",
        destination: `${apiOrigin}/:path*`,
      },
    ];
  },
};

export default nextConfig;
