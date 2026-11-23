import { createMcpHandler, McpServer } from "@modelcontextprotocol/server";
import * as z from "zod/v4";
import { LeaderboardService } from "./service.js";
import { EnvLarkBaseStore } from "./store.js";
import { oauthConfigFromEnv, resourceMetadataUrl, verifyAccessToken } from "./oauth.js";

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

/**
 * Build the server for one authenticated person. `subject` comes from the verified OAuth access token
 * (the openTag per-app user ID), so no tool accepts an identity argument.
 */
export function buildServer(subject: string, service = new LeaderboardService(new EnvLarkBaseStore())): McpServer {
  const server = new McpServer({ name: "meiri-baoji-leaderboard", version: "0.1.0" });

  server.registerTool(
    "create_leaderboard",
    {
      description: "Create a leaderboard with the confirmed default diet, exercise, and thin-muscle dimensions; others join it by name. Names are unique (case-insensitive): NAME_TAKEN means pick another or join the existing one. The signed-in person becomes its creator.",
      inputSchema: z.object({
        name: z.string().min(1).max(40).describe("Name users will say to join it"),
        timezone: z.string().min(1).describe("One IANA timezone shared by the leaderboard, such as Asia/Shanghai")
      })
    },
    (input) => toolResult(() => service.createLeaderboard({ ...input, creator_subject: subject }))
  );

  server.registerTool(
    "join_leaderboard",
    {
      description: "Join or rejoin an existing leaderboard as the signed-in person, by its name (or a known ID). NOT_FOUND means no leaderboard has that name.",
      inputSchema: z.object({
        name: z.string().optional().describe("Leaderboard name as the user said it (matched case-insensitively)"),
        leaderboard_id: z.string().optional().describe("Only if already known from an earlier result; users never see IDs"),
        display_name: z.string().min(1).max(40)
      })
    },
    (input) => toolResult(() => service.join({ ...input, member_subject: subject }))
  );

  server.registerTool(
    "leave_leaderboard",
    {
      description: "Leave a leaderboard. Existing score snapshots remain for historical rankings.",
      inputSchema: z.object({ name: z.string().optional(), leaderboard_id: z.string().optional() })
    },
    (input) => toolResult(() => service.leave({ ...input, member_subject: subject }))
  );

  server.registerTool(
    "get_leaderboard_definition",
    {
      description: "Get active dimensions and exact criteria versions for the current cycle. Cache this definition until next_cycle_start; do not fetch it before every score.",
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
        dimension_id: z.string(),
        name: z.string(),
        description: z.string(),
        criteria_text: z.string().min(1).describe("One natural-language scoring policy")
      })
    },
    (input) => toolResult(() => service.addDimension({ ...input, actor_subject: subject }))
  );

  server.registerTool(
    "update_scoring_criteria",
    {
      description: "Create a new criteria version for one dimension. It takes effect at the next weekly cycle.",
      inputSchema: z.object({
        leaderboard_id: z.string(),
        dimension_id: z.string(),
        criteria_text: z.string().min(1).describe("One natural-language scoring policy")
      })
    },
    (input) => toolResult(() => service.updateCriteria({ ...input, actor_subject: subject }))
  );

  server.registerTool(
    "submit_daily_update",
    {
      description: "Submit all current 0-100 dimension scores. The server chooses the date from the leaderboard timezone; a later submission replaces that day's final snapshot. STALE_CRITERIA means refresh the definition and recalculate.",
      inputSchema: z.object({
        leaderboard_id: z.string(),
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
    (input) => toolResult(() => service.submitDailyUpdate({ ...input, member_subject: subject }))
  );

  server.registerTool(
    "get_leaderboard",
    {
      description: "Get the current daily or weekly ranking. Weekly score is the sum of each day's final snapshot, never an average.",
      inputSchema: z.object({
        name: z.string().optional(),
        leaderboard_id: z.string().optional(),
        period: z.enum(["day", "week"]),
        dimension_id: z.string().optional()
      })
    },
    (input) => toolResult(() => service.getLeaderboard(input))
  );

  return server;
}

export function createLeaderboardHandler(service = new LeaderboardService(new EnvLarkBaseStore())) {
  return createMcpHandler(
    (ctx) => {
      const subject = ctx.authInfo?.extra?.subject;
      if (typeof subject !== "string" || !subject) throw new Error("An authenticated subject is required");
      return buildServer(subject, service);
    },
    { responseMode: "json" }
  );
}

const defaultHandler = createLeaderboardHandler();

function unauthorized(message: string, status: number, challenge?: string): Response {
  return Response.json(
    { error: status === 401 ? "invalid_token" : "server_error", error_description: message },
    { status, headers: challenge ? { "WWW-Authenticate": challenge } : {} }
  );
}

export async function handleMcpRequest(request: Request, handler = defaultHandler): Promise<Response> {
  const config = oauthConfigFromEnv();
  if (!config) return unauthorized("OAuth is not configured", 503);
  const challenge = `Bearer resource_metadata="${resourceMetadataUrl(config)}", scope="leaderboard"`;
  const header = request.headers.get("authorization") || "";
  const supplied = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  const claims = supplied ? verifyAccessToken(config, supplied) : undefined;
  if (!claims) return unauthorized(supplied ? "Invalid or expired access token" : "Sign in with openTag is required", 401, challenge);

  const origin = request.headers.get("origin");
  const allowed = (process.env.MCP_ALLOWED_ORIGINS || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  if (origin && allowed.length && !allowed.includes(origin)) {
    return Response.json({ error: "Origin is not allowed" }, { status: 403 });
  }
  return handler.fetch(request, {
    authInfo: {
      token: supplied,
      clientId: claims.cid,
      scopes: [claims.scope],
      expiresAt: claims.exp,
      resource: new URL(`${config.publicUrl}/api/mcp`),
      extra: { subject: `opentag:${claims.sub}` }
    }
  });
}
