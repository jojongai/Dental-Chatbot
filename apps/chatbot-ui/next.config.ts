import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["@dental-chatbot/shared-types"],
};

export default nextConfig;
