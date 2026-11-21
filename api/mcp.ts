import { handleMcpRequest } from "../src/mcp.js";

export const maxDuration = 30;

export default {
  fetch(request: Request): Promise<Response> {
    return handleMcpRequest(request);
  }
};
