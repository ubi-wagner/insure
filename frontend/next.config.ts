import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow large file uploads (500MB) through the API proxy
  experimental: {
    serverActions: {
      bodySizeLimit: "500mb",
    },
  },
  // Increase API route body size limit
  api: {
    bodyParser: {
      sizeLimit: "500mb",
    },
  },
};

export default nextConfig;
