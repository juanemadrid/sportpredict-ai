/** @type {import('next').NextConfig} */
const isGithubPages = process.env.GITHUB_PAGES === "true" || process.env.GITHUB_ACTIONS === "true";
const basePath = isGithubPages ? "/sportpredict-ai" : "";

const nextConfig = {
  reactStrictMode: true,
  output: isGithubPages ? "export" : (process.env.DOCKER_BUILD === "1" ? "standalone" : undefined),
  basePath: basePath,
  assetPrefix: basePath ? `${basePath}/` : undefined,
  images: {
    unoptimized: true,
  },
  env: {
    NEXT_PUBLIC_BASE_PATH: basePath,
  },
};

export default nextConfig;
