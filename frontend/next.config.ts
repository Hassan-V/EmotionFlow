import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  async headers() {
    return [
      {
        source: "/meet/:path*",
        headers: [
          { key: "Content-Security-Policy", value: "frame-ancestors 'self' https://meet.google.com" },
          { key: "Permissions-Policy", value: "microphone=(self \"https://meet.google.com\")" },
        ],
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/:path*`,
      },
    ];
  },
};

export default nextConfig;
