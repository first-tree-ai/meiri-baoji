import { timingSafeEqual } from "node:crypto";
import { createMcpHandler, McpServer } from "@modelcontextprotocol/server";
import * as z from "zod/v4";
import { LeaderboardService } from "./service.js";
import { EnvLarkBaseStore } from "./store.js";

function jsonResult(value: unknown) {
  return { content: [{ type: "text" as const, text: JSON.stringify(value, null, 2) }] };
}

function toolResult(action: () => Promise<unknown>) {
  return action()
    .then(jsonResult)
    .catch((error: unknown) => ({
      isError: true,
      content: [{ type: "text" as const, text: error instanceof Error ? error.message : "Unknown error" }]
    }));
}

export function buildServer(service = new LeaderboardService(new EnvLarkBaseStore())): McpServer {
  const server = new McpServer({ name: "meiri-baoji-leaderboard", version: "0.1.0" });

  server.registerTool(
    "create_leaderboard",
    {
      description: "Bootstrap a leaderboard with the confirmed default diet, exercise, and thin-muscle dimensions.",
      inputSchema: z.object({
        name: z.string().min(1),
        timezone: z.string().min(1).describe("One IANA timezone shared by the leaderboard, such as Asia/Shanghai"),
        creator_subject: z.string().min(1)
      })
    },
    (input) => toolResult(() => service.createLeaderboard(input))
  );

  server.registerTool(
    "join_leaderboard",
    {
      description: "Join or rejoin an existing leaderboard.",
      inputSchema: z.object({ leaderboard_id: z.string(), member_subject: z.string(), display_name: z.string() })
    },
    (input) => toolResult(() => service.join(input))
  );

  server.registerTool(
    "leave_leaderboard",
    {
      description: "Leave a leaderboard. Existing score snapshots remain for historical rankings.",
      inputSchema: z.object({ leaderboard_id: z.string(), member_subject: z.string() })
    },
    (input) => toolResult(() => service.leave(input))
  );

  server.registerTool(
    "get_leaderboard_definition",
    {
      description: "Get active dimensions and the exact criteria version to use for the current cycle.",
      inputSchema: z.object({ leaderboard_id: z.string() })
    },
    (input) => toolResult(() => service.getDefinition(input))
  );

  server.registerTool(
    "add_dimension",
    {
      description: "Append a scoring dimension. Dimensions cannot be deleted in the MVP and become active next cycle.",
      inputSchema: z.object({
        leaderboard_id: z.string(),
        actor_subject: z.string(),
        dimension_id: z.string(),
        name: z.string(),
        description: z.string(),
        criteria_text: z.string().min(1).describe("One natural-language scoring policy")
      })
    },
    (input) => toolResult(() => service.addDimension(input))
  );

  server.registerTool(
    "update_scoring_criteria",
    {
      description: "Create a new criteria version for one dimension. It takes effect at the next weekly cycle.",
      inputSchema: z.object({
        leaderboard_id: z.string(),
        actor_subject: z.string(),
        dimension_id: z.string(),
        criteria_text: z.string().min(1).describe("One natural-language scoring policy")
      })
    },
    (input) => toolResult(() => service.updateCriteria(input))
  );

  server.registerTool(
    "submit_daily_update",
    {
      description: "Submit all current 0-100 dimension scores. The server chooses the date from the leaderboard timezone; a later submission replaces that day's final snapshot.",
      inputSchema: z.object({
        leaderboard_id: z.string(),
        member_subject: z.string(),
        idempotency_key: z.string().min(1),
        scores: z.array(
          z.object({
            dimension_id: z.string(),
            score: z.number().min(0).max(100),
            criteria_version_id: z.string()
          })
        )
      })
    },
    (input) => toolResult(() => service.submitDailyUpdate(input))
  );

  server.registerTool(
    "get_leaderboard",
    {
      description: "Get the current daily or weekly ranking. Weekly score is the sum of each day's final snapshot, never an average.",
      inputSchema: z.object({
        leaderboard_id: z.string(),
        period: z.enum(["day", "week"]),
        dimension_id: z.string().optional()
      })
    },
    (input) => toolResult(() => service.getLeaderboard(input))
  );

  return server;
}

export const mcpHandler = createMcpHandler(() => buildServer(), { responseMode: "json" });

function unauthorized(message: string, status: number): Response {
  return Response.json({ error: message }, { status, headers: { "WWW-Authenticate": "Bearer" } });
}

function constantTimeEqual(left: string, right: string): boolean {
  const a = Buffer.from(left);
  const b = Buffer.from(right);
  return a.length === b.length && timingSafeEqual(a, b);
}

export async function handleMcpRequest(request: Request): Promise<Response> {
  const expected = process.env.MCP_BEARER_TOKEN?.trim();
  if (!expected) return unauthorized("MCP_BEARER_TOKEN is not configured", 503);
  const header = request.headers.get("authorization") || "";
  const supplied = header.startsWith("Bearer ") ? header.slice(7) : "";
  if (!supplied || !constantTimeEqual(supplied, expected)) return unauthorized("Invalid bearer token", 401);

  const origin = request.headers.get("origin");
  const allowed = (process.env.MCP_ALLOWED_ORIGINS || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  if (origin && allowed.length && !allowed.includes(origin)) {
    return Response.json({ error: "Origin is not allowed" }, { status: 403 });
  }
  return mcpHandler.fetch(request);
}
