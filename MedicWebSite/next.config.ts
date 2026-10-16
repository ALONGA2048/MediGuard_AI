import type { NextConfig } from "next";

const allowedDevOrigins = (process.env.MEDIGUARD_ALLOWED_DEV_ORIGINS ?? "210.240.160.148")
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean);

const nextConfig: NextConfig = {
  allowedDevOrigins,
};

export default nextConfig;
