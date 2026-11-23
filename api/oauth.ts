import { handleOAuthRequest } from "../src/oauth.js";

export const maxDuration = 30;

// Rewrites in vercel.json route the well-known documents and /oauth/* here with ?op=<endpoint>.
export default {
  fetch(request: Request): Promise<Response> {
    const op = new URL(request.url).searchParams.get("op") || "";
    return handleOAuthRequest(request, op);
  }
};
