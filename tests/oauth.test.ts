import assert from "node:assert/strict";
import { createHash, randomBytes } from "node:crypto";
import test, { beforeEach } from "node:test";
import { createLeaderboardHandler, handleMcpRequest } from "../src/mcp.js";
import { handleOAuthRequest, resetUpstreamCache, type Fetch } from "../src/oauth.js";
import { LeaderboardService } from "../src/service.js";
import { MemoryStore } from "../src/store.js";
import { TABLES } from "../src/types.js";

const PUBLIC = "https://baoji.example";
const ISSUER = "https://opentag.example/api/v1/auth";
const CLIENT_REDIRECT = "https://opentag.example/api/v1/mcp-servers/oauth/callback";

beforeEach(() => {
  process.env.MCP_PUBLIC_URL = PUBLIC;
  process.env.MCP_OAUTH_SECRET = "s".repeat(40);
  process.env.OPENTAG_OAUTH_ISSUER = ISSUER;
  process.env.OPENTAG_OAUTH_CLIENT_ID = "upstream-client";
  process.env.OPENTAG_OAUTH_CLIENT_SECRET = "upstream-secret";
  delete process.env.MCP_ALLOWED_ORIGINS;
  resetUpstreamCache();
});

/** A fake openTag provider: discovery, token, and userinfo. */
function fakeOpenTag(sub = "pairwise-alice") {
  const calls: Array<{ url: string; body?: string }> = [];
  const fetcher: Fetch = async (url, init) => {
    calls.push({ url, body: typeof init?.body === "string" ? init.body : undefined });
    if (url === `${ISSUER}/.well-known/openid-configuration`) {
      return Response.json({
        issuer: ISSUER,
        authorization_endpoint: `${ISSUER}/oauth2/authorize`,
        token_endpoint: `${ISSUER}/oauth2/token`,
        userinfo_endpoint: `${ISSUER}/oauth2/userinfo`
      });
    }
    if (url === `${ISSUER}/oauth2/token`) {
      const form = new URLSearchParams(init?.body as string);
      if (form.get("code") !== "upstream-code" || form.get("client_secret") !== "upstream-secret") {
        return Response.json({ error: "invalid_grant" }, { status: 400 });
      }
      return Response.json({ access_token: "upstream-at", token_type: "Bearer" });
    }
    if (url === `${ISSUER}/oauth2/userinfo`) return Response.json({ sub });
    return new Response("not found", { status: 404 });
  };
  return { fetcher, calls };
}

async function registerClient() {
  const response = await handleOAuthRequest(
    new Request(`${PUBLIC}/oauth/register`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        application_type: "web",
        redirect_uris: [CLIENT_REDIRECT],
        grant_types: ["authorization_code", "refresh_token"],
        response_types: ["code"],
        token_endpoint_auth_method: "client_secret_basic",
        client_name: "openTag"
      })
    }),
    "register"
  );
  assert.equal(response.status, 201);
  return (await response.json()) as { client_id: string; client_secret: string };
}

function basic(clientId: string, secret: string): string {
  return `Basic ${Buffer.from(`${clientId}:${secret}`).toString("base64")}`;
}

async function signIn(fake = fakeOpenTag()) {
  const client = await registerClient();
  const verifier = randomBytes(32).toString("base64url");
  const challenge = createHash("sha256").update(verifier).digest("base64url");
  const authorizeUrl = new URL(`${PUBLIC}/oauth/authorize`);
  authorizeUrl.search = new URLSearchParams({
    response_type: "code",
    client_id: client.client_id,
    redirect_uri: CLIENT_REDIRECT,
    state: "client-state",
    code_challenge: challenge,
    code_challenge_method: "S256",
    resource: `${PUBLIC}/api/mcp`,
    scope: "leaderboard"
  }).toString();
  const authorize = await handleOAuthRequest(new Request(authorizeUrl), "authorize", fake.fetcher);
  assert.equal(authorize.status, 302);
  const upstream = new URL(authorize.headers.get("location")!);
  assert.equal(upstream.origin + upstream.pathname, `${ISSUER}/oauth2/authorize`);
  assert.equal(upstream.searchParams.get("client_id"), "upstream-client");
  assert.equal(upstream.searchParams.get("redirect_uri"), `${PUBLIC}/oauth/callback`);
  assert.equal(upstream.searchParams.get("code_challenge_method"), "S256");
  const cookie = authorize.headers.get("set-cookie")!.split(";")[0];

  const callbackUrl = new URL(`${PUBLIC}/oauth/callback`);
  callbackUrl.search = new URLSearchParams({ code: "upstream-code", state: upstream.searchParams.get("state")!, iss: ISSUER }).toString();
  const callback = await handleOAuthRequest(new Request(callbackUrl, { headers: { cookie } }), "callback", fake.fetcher);
  assert.equal(callback.status, 302);
  const back = new URL(callback.headers.get("location")!);
  assert.equal(back.origin + back.pathname, CLIENT_REDIRECT);
  assert.equal(back.searchParams.get("state"), "client-state");
  assert.equal(back.searchParams.get("iss"), PUBLIC);
  const code = back.searchParams.get("code")!;
  assert.ok(code);
  return { client, verifier, code, cookie, upstreamState: upstream.searchParams.get("state")!, fake };
}

async function exchange(clientId: string, secret: string, form: Record<string, string>) {
  return handleOAuthRequest(
    new Request(`${PUBLIC}/oauth/token`, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded", authorization: basic(clientId, secret) },
      body: new URLSearchParams(form).toString()
    }),
    "token"
  );
}

test("metadata advertises this server as the authorization server with DCR and S256", async () => {
  const prm = (await (await handleOAuthRequest(new Request(`${PUBLIC}/.well-known/oauth-protected-resource/api/mcp`), "prm")).json()) as Record<string, unknown>;
  assert.equal(prm.resource, `${PUBLIC}/api/mcp`);
  assert.deepEqual(prm.authorization_servers, [PUBLIC]);
  const as = (await (await handleOAuthRequest(new Request(`${PUBLIC}/.well-known/oauth-authorization-server`), "as")).json()) as Record<string, unknown>;
  assert.equal(as.issuer, PUBLIC);
  assert.equal(as.registration_endpoint, `${PUBLIC}/oauth/register`);
  assert.deepEqual(as.code_challenge_methods_supported, ["S256"]);
});

test("full flow: register, sign in with openTag, exchange with PKCE, refresh", async () => {
  const { client, verifier, code } = await signIn();
  const response = await exchange(client.client_id, client.client_secret, {
    grant_type: "authorization_code",
    code,
    redirect_uri: CLIENT_REDIRECT,
    code_verifier: verifier,
    resource: `${PUBLIC}/api/mcp`
  });
  assert.equal(response.status, 200);
  const tokens = (await response.json()) as Record<string, string>;
  assert.equal(tokens.token_type, "Bearer");
  assert.ok(tokens.access_token.startsWith("mba_"));
  const refreshed = await exchange(client.client_id, client.client_secret, {
    grant_type: "refresh_token",
    refresh_token: tokens.refresh_token,
    resource: `${PUBLIC}/api/mcp`
  });
  assert.equal(refreshed.status, 200);
  assert.ok(((await refreshed.json()) as Record<string, string>).access_token.startsWith("mba_"));
});

test("token endpoint rejects a wrong PKCE verifier, a wrong client secret, and another client's code", async () => {
  const { client, code } = await signIn();
  const wrongVerifier = await exchange(client.client_id, client.client_secret, {
    grant_type: "authorization_code",
    code,
    code_verifier: randomBytes(32).toString("base64url")
  });
  assert.equal(((await wrongVerifier.json()) as Record<string, string>).error, "invalid_grant");
  const wrongSecret = await exchange(client.client_id, "nope", { grant_type: "authorization_code", code, code_verifier: "x" });
  assert.equal(wrongSecret.status, 401);
  const other = await registerClient();
  const stolen = await exchange(other.client_id, other.client_secret, { grant_type: "authorization_code", code, code_verifier: "x" });
  assert.equal(((await stolen.json()) as Record<string, string>).error, "invalid_grant");
});

test("authorize refuses unregistered redirect URIs without redirecting", async () => {
  const client = await registerClient();
  const url = new URL(`${PUBLIC}/oauth/authorize`);
  url.search = new URLSearchParams({
    response_type: "code",
    client_id: client.client_id,
    redirect_uri: "https://evil.example/cb",
    code_challenge: "a".repeat(43),
    code_challenge_method: "S256"
  }).toString();
  const response = await handleOAuthRequest(new Request(url), "authorize", fakeOpenTag().fetcher);
  assert.equal(response.status, 400);
  assert.equal(response.headers.get("location"), null);
});

test("callback refuses a transaction started in another browser", async () => {
  const { upstreamState, fake } = await signIn();
  const url = new URL(`${PUBLIC}/oauth/callback`);
  url.search = new URLSearchParams({ code: "upstream-code", state: upstreamState }).toString();
  const response = await handleOAuthRequest(new Request(url, { headers: { cookie: "mb_oauth_tx=other" } }), "callback", fake.fetcher);
  assert.equal(response.status, 400);
});

/** The legacy stateless leg answers over SSE; read the JSON-RPC message from either shape. */
async function rpcBody<T>(response: Response): Promise<T> {
  const text = await response.text();
  const data = text.startsWith("{") ? text : text.split("\n").find((line) => line.startsWith("data: "))!.slice(6);
  return JSON.parse(data) as T;
}

async function accessToken(sub: string) {
  const { client, verifier, code } = await signIn(fakeOpenTag(sub));
  const response = await exchange(client.client_id, client.client_secret, { grant_type: "authorization_code", code, code_verifier: verifier });
  return ((await response.json()) as Record<string, string>).access_token;
}

function rpc(id: number, method: string, params: Record<string, unknown>, token?: string) {
  return new Request(`${PUBLIC}/api/mcp`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "application/json, text/event-stream",
      "mcp-protocol-version": "2025-06-18",
      ...(token ? { authorization: `Bearer ${token}` } : {})
    },
    body: JSON.stringify({ jsonrpc: "2.0", id, method, params })
  });
}

test("MCP endpoint challenges unauthenticated calls with the resource metadata URL", async () => {
  const response = await handleMcpRequest(rpc(1, "tools/list", {}));
  assert.equal(response.status, 401);
  assert.match(response.headers.get("www-authenticate")!, /resource_metadata="https:\/\/baoji\.example\/\.well-known\/oauth-protected-resource\/api\/mcp"/);
  const forged = await handleMcpRequest(rpc(1, "tools/list", {}, "mba_forged"));
  assert.equal(forged.status, 401);
});

test("tools take identity from the token, never from arguments", async () => {
  const store = new MemoryStore();
  const service = new LeaderboardService(store);
  const handler = createLeaderboardHandler(service);
  const created = await service.createLeaderboard({ name: "榜", timezone: "Asia/Shanghai", creator_subject: "opentag:creator" });
  const token = await accessToken("pairwise-alice");

  const list = await handleMcpRequest(rpc(1, "tools/list", {}, token), handler);
  assert.equal(list.status, 200);
  const tools = (await rpcBody<{ result: { tools: Array<{ name: string; inputSchema: { properties?: Record<string, unknown> } }> } }>(list)).result.tools;
  assert.equal(tools.length, 8);
  for (const tool of tools) {
    for (const field of ["member_subject", "creator_subject", "actor_subject"]) {
      assert.equal(field in (tool.inputSchema.properties || {}), false, `${tool.name} exposes ${field}`);
    }
  }

  const join = await handleMcpRequest(
    rpc(2, "tools/call", { name: "join_leaderboard", arguments: { leaderboard_id: created.leaderboard_id, display_name: "小A" } }, token),
    handler
  );
  assert.equal(join.status, 200);
  // The legacy leg streams over SSE: the tool finishes only once the body is read.
  await join.text();
  const members = await store.list(TABLES.members);
  assert.equal(members.length, 1);
  assert.equal(members[0].fields.member_subject, "opentag:pairwise-alice");

  const update = await handleMcpRequest(
    rpc(3, "tools/call", { name: "update_scoring_criteria", arguments: { leaderboard_id: created.leaderboard_id, dimension_id: "diet", criteria_text: "x" } }, token),
    handler
  );
  const body = await rpcBody<{ result: { isError?: boolean; content: Array<{ text: string }> } }>(update);
  assert.equal(body.result.isError, true);
  assert.match(body.result.content[0].text, /Only the leaderboard creator/);
});
