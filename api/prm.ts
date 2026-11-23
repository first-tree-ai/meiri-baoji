import { authConfigFromEnv, protectedResourceMetadata } from "../src/auth.js";

// vercel.json rewrites both well-known PRM paths here.
export default {
  fetch(): Response {
    const config = authConfigFromEnv();
    if (!config) return Response.json({ error: "Auth is not configured" }, { status: 503 });
    return protectedResourceMetadata(config);
  }
};
