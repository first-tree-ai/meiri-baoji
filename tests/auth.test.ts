import assert from "node:assert/strict";
import test, { beforeEach } from "node:test";
import { createLocalJWKSet, exportJWK, generateKeyPair, SignJWT, type JWTPayload } from "jose";
import { protectedResourceMetadata, verifyAgentToken } from "../src/auth.js";
import { createLeaderboardHandler, handleMcpRequest } from "../src/mcp.js";
import { LeaderboardService } from "../src/service.js";
import { MemoryStore } from "../src/store.js";
import { TABLES } from "../src/types.js";

const PUBLIC = "https://baoji.example";
const ISSUER = "https://opentag.example/api/v1/auth";
const RESOURCE = `${PUBLIC}/api/mcp`;
const config = { publicUrl: PUBLIC, issuer: ISSUER };

// A mock openTag JWKS with the same key type staging publishes (EdDSA / Ed25519).
const { publicKey, privateKey } = await generateKeyPair("EdDSA", { crv: "Ed25519" });
const other = await generateKeyPair("EdDSA", { crv: "Ed25519" });
const jwk = { ...(await exportJWK(publicKey)), kid: "k1", alg: "EdDSA" };
const keys = createLocalJWKSet({ keys: [jwk] });

beforeEach(() => {
  process.env.MCP_PUBLIC_URL = PUBLIC;
  process.env.OPENTAG_OAUTH_ISSUER = ISSUER;
  delete process.env.MCP_ALLOWED_ORIGINS;
});

async function token(claims: JWTPayload = {}, options: { lifetime?: number; key?: CryptoKey; iat?: number; aud?: string; iss?: string } = {}) {
  const iat = options.iat ?? Math.floor(Date.now() / 1000);
  return new SignJWT({ opentag_subject_type: "agent", scope: "mcp", client_id: "pairwise-agent-1", azp: "pairwise-agent-1", ...claims })
    .setProtectedHeader({ alg: "EdDSA", kid: "k1" })
    .setIssuer(options.iss ?? ISSUER)
    .setAudience(options.aud ?? RESOURCE)
    .setSubject("pairwise-agent-1")
    .setIssuedAt(iat)
    .setExpirationTime(iat + (options.lifetime ?? 600))
    .sign(options.key ?? privateKey);
}

test("PRM names openTag as the authorization server and declares agent mode", async () => {
  const body = (await protectedResourceMetadata(config).json()) as Record<string, unknown>;
  assert.equal(body.resource, RESOURCE);
  assert.deepEqual(body.authorization_servers, [ISSUER]);
  assert.equal(body.opentag_auth_mode, "agent");
});

test("accepts an openTag agent token for this resource and derives agent:<sub>", async () => {
  const identity = await verifyAgentToken(config, await token(), keys);
  assert.equal(identity?.subject, "agent:pairwise-agent-1");
  assert.deepEqual(identity?.scopes, ["mcp"]);
});

test("rejects wrong audience, issuer, signer, subject type, expiry and over-long lifetime", async () => {
  const cases = [
    await token({}, { aud: "https://other.example/api/mcp" }),
    await token({}, { iss: "https://evil.example" }),
    await token({}, { key: other.privateKey }),
    await token({ opentag_subject_type: "user" }),
    await token({}, { iat: Math.floor(Date.now() / 1000) - 3600 }),
    await token({}, { lifetime: 24 * 3600 }),
    "not-a-jwt"
  ];
  for (const value of cases) assert.equal(await verifyAgentToken(config, value, keys), undefined);
});

function rpc(id: number, method: string, params: Record<string, unknown>, bearer?: string) {
  return new Request(RESOURCE, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "application/json, text/event-stream",
      "mcp-protocol-version": "2025-06-18",
      ...(bearer ? { authorization: `Bearer ${bearer}` } : {})
    },
    body: JSON.stringify({ jsonrpc: "2.0", id, method, params })
  });
}

/** The legacy stateless leg answers over SSE; read the JSON-RPC message from either shape. */
async function rpcBody<T>(response: Response): Promise<T> {
  const text = await response.text();
  const data = text.startsWith("{") ? text : text.split("\n").find((line) => line.startsWith("data: "))!.slice(6);
  return JSON.parse(data) as T;
}

test("MCP endpoint challenges calls without a valid token with the PRM URL", async () => {
  const response = await handleMcpRequest(rpc(1, "tools/list", {}), undefined, keys);
  assert.equal(response.status, 401);
  assert.equal(
    response.headers.get("www-authenticate"),
    `Bearer resource_metadata="${PUBLIC}/.well-known/oauth-protected-resource/api/mcp"`
  );
  const forged = await handleMcpRequest(rpc(1, "tools/list", {}, await token({}, { key: other.privateKey })), undefined, keys);
  assert.equal(forged.status, 401);
});

test("tools take identity from the token, never from arguments", async () => {
  const store = new MemoryStore();
  const service = new LeaderboardService(store);
  const handler = createLeaderboardHandler(service);
  const created = await service.createLeaderboard({ name: "榜", timezone: "Asia/Shanghai", creator_subject: "agent:creator" });
  const bearer = await token();

  const list = await handleMcpRequest(rpc(1, "tools/list", {}, bearer), handler, keys);
  assert.equal(list.status, 200);
  const tools = (await rpcBody<{ result: { tools: Array<{ name: string; inputSchema: { properties?: Record<string, unknown> } }> } }>(list)).result.tools;
  assert.equal(tools.length, 8);
  for (const tool of tools) {
    for (const field of ["member_subject", "creator_subject", "actor_subject"]) {
      assert.equal(field in (tool.inputSchema.properties || {}), false, `${tool.name} exposes ${field}`);
    }
  }

  const join = await handleMcpRequest(
    rpc(2, "tools/call", { name: "join_leaderboard", arguments: { leaderboard_id: created.leaderboard_id, display_name: "小A" } }, bearer),
    handler,
    keys
  );
  assert.equal(join.status, 200);
  // The legacy leg streams over SSE: the tool finishes only once the body is read.
  await join.text();
  const members = await store.list(TABLES.members);
  assert.equal(members.length, 1);
  assert.equal(members[0].fields.member_subject, "agent:pairwise-agent-1");

  const update = await handleMcpRequest(
    rpc(3, "tools/call", { name: "update_scoring_criteria", arguments: { leaderboard_id: created.leaderboard_id, dimension_id: "diet", criteria_text: "x" } }, bearer),
    handler,
    keys
  );
  const body = await rpcBody<{ result: { isError?: boolean; content: Array<{ text: string }> } }>(update);
  assert.equal(body.result.isError, true);
  assert.match(body.result.content[0].text, /Only the leaderboard creator/);
});
