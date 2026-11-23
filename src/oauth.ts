import { createCipheriv, createDecipheriv, createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";

/*
 * OAuth 2.1 authorization server for the MCP endpoint, with RFC 7591 Dynamic Client Registration.
 * People sign in with their openTag Account ("Sign in with openTag"); the leaderboard identity is the
 * openTag per-app user ID (`sub`), never a tool argument.
 *
 * Everything this server issues (client IDs, the upstream transaction, authorization codes, access and
 * refresh tokens) is sealed with AES-256-GCM under MCP_OAUTH_SECRET, so nothing is stored. Rotating the
 * secret invalidates every client and token; clients then register and authorize again.
 */

export const MCP_PATH = "/api/mcp";
export const SCOPE = "leaderboard";
const TX_COOKIE = "mb_oauth_tx";
const TX_TTL_SECONDS = 600;
const CODE_TTL_SECONDS = 60;
const ACCESS_TTL_SECONDS = 3600;
const REFRESH_TTL_SECONDS = 30 * 24 * 3600;

export interface OAuthConfig {
  publicUrl: string;
  secret: string;
  upstreamIssuer: string;
  upstreamClientId: string;
  upstreamClientSecret: string;
}

export type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

export interface AccessTokenClaims {
  sub: string;
  cid: string;
  scope: string;
  exp: number;
}

export function oauthConfigFromEnv(env: NodeJS.ProcessEnv = process.env): OAuthConfig | undefined {
  const publicUrl = env.MCP_PUBLIC_URL?.trim().replace(/\/+$/, "");
  const secret = env.MCP_OAUTH_SECRET?.trim();
  const upstreamIssuer = env.OPENTAG_OAUTH_ISSUER?.trim().replace(/\/+$/, "");
  const upstreamClientId = env.OPENTAG_OAUTH_CLIENT_ID?.trim();
  const upstreamClientSecret = env.OPENTAG_OAUTH_CLIENT_SECRET?.trim();
  if (!publicUrl || !secret || secret.length < 32 || !upstreamIssuer || !upstreamClientId || !upstreamClientSecret) {
    return undefined;
  }
  return { publicUrl, secret, upstreamIssuer, upstreamClientId, upstreamClientSecret };
}

export function resourceUrl(config: OAuthConfig): string {
  return `${config.publicUrl}${MCP_PATH}`;
}

export function resourceMetadataUrl(config: OAuthConfig): string {
  return `${config.publicUrl}/.well-known/oauth-protected-resource${MCP_PATH}`;
}

// ---- sealing ----

function key(config: OAuthConfig, purpose: string): Buffer {
  return createHash("sha256").update(`meiri-baoji-oauth|${purpose}|${config.secret}`).digest();
}

function seal(config: OAuthConfig, typ: string, payload: Record<string, unknown>): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key(config, "seal"), iv);
  cipher.setAAD(Buffer.from(typ));
  const body = Buffer.concat([cipher.update(JSON.stringify(payload), "utf8"), cipher.final()]);
  return Buffer.concat([iv, body, cipher.getAuthTag()]).toString("base64url");
}

function unseal(config: OAuthConfig, typ: string, value: string | null | undefined): Record<string, unknown> | undefined {
  if (!value || value.length > 4096) return undefined;
  try {
    const raw = Buffer.from(value, "base64url");
    if (raw.length < 29) return undefined;
    const decipher = createDecipheriv("aes-256-gcm", key(config, "seal"), raw.subarray(0, 12));
    decipher.setAAD(Buffer.from(typ));
    decipher.setAuthTag(raw.subarray(raw.length - 16));
    const text = Buffer.concat([decipher.update(raw.subarray(12, raw.length - 16)), decipher.final()]).toString("utf8");
    const payload = JSON.parse(text) as Record<string, unknown>;
    if (typeof payload.exp === "number" && payload.exp < nowSeconds()) return undefined;
    return payload;
  } catch {
    return undefined;
  }
}

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

function equal(left: string, right: string): boolean {
  const a = Buffer.from(left);
  const b = Buffer.from(right);
  return a.length === b.length && timingSafeEqual(a, b);
}

function s256(verifier: string): string {
  return createHash("sha256").update(verifier).digest("base64url");
}

// ---- clients (RFC 7591) ----

const CLIENT_PREFIX = "mbc_";

interface Client {
  id: string;
  redirectUris: string[];
}

function clientSecret(config: OAuthConfig, clientId: string): string {
  return createHmac("sha256", key(config, "client-secret")).update(clientId).digest("base64url");
}

function readClient(config: OAuthConfig, clientId: string | null | undefined): Client | undefined {
  if (!clientId?.startsWith(CLIENT_PREFIX)) return undefined;
  const payload = unseal(config, "client", clientId.slice(CLIENT_PREFIX.length));
  const redirectUris = payload?.ru;
  if (!Array.isArray(redirectUris) || !redirectUris.every((uri) => typeof uri === "string")) return undefined;
  return { id: clientId, redirectUris: redirectUris as string[] };
}

function validRedirectUri(value: unknown): value is string {
  if (typeof value !== "string" || value.length > 512) return false;
  try {
    const url = new URL(value);
    if (url.hash) return false;
    if (url.protocol === "https:") return true;
    return url.protocol === "http:" && (url.hostname === "localhost" || url.hostname === "127.0.0.1");
  } catch {
    return false;
  }
}

// ---- responses ----

function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return Response.json(body, { status, headers: { "cache-control": "no-store", ...headers } });
}

function oauthError(error: string, description: string, status = 400, headers: Record<string, string> = {}): Response {
  return json({ error, error_description: description }, status, headers);
}

function redirect(location: string, headers: Record<string, string> = {}): Response {
  return new Response(null, { status: 302, headers: { location, "cache-control": "no-store", ...headers } });
}

function page(message: string, status = 400): Response {
  return new Response(message, { status, headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" } });
}

function cookie(request: Request, name: string): string | undefined {
  for (const part of (request.headers.get("cookie") || "").split(";")) {
    const [k, ...v] = part.trim().split("=");
    if (k === name) return v.join("=");
  }
  return undefined;
}

// ---- metadata ----

export function protectedResourceMetadata(config: OAuthConfig): Response {
  return json(
    {
      resource: resourceUrl(config),
      authorization_servers: [config.publicUrl],
      scopes_supported: [SCOPE],
      bearer_methods_supported: ["header"],
      resource_name: "薄肌教练排行榜"
    },
    200,
    { "access-control-allow-origin": "*" }
  );
}

export function authorizationServerMetadata(config: OAuthConfig): Response {
  const base = config.publicUrl;
  return json(
    {
      issuer: base,
      authorization_endpoint: `${base}/oauth/authorize`,
      token_endpoint: `${base}/oauth/token`,
      registration_endpoint: `${base}/oauth/register`,
      response_types_supported: ["code"],
      grant_types_supported: ["authorization_code", "refresh_token"],
      code_challenge_methods_supported: ["S256"],
      token_endpoint_auth_methods_supported: ["client_secret_basic", "client_secret_post"],
      scopes_supported: [SCOPE],
      authorization_response_iss_parameter_supported: true
    },
    200,
    { "access-control-allow-origin": "*" }
  );
}

// ---- upstream openTag ----

interface UpstreamMetadata {
  authorization_endpoint: string;
  token_endpoint: string;
  userinfo_endpoint: string;
}

let upstreamCache: { issuer: string; value: UpstreamMetadata; expiresAt: number } | undefined;

async function upstreamMetadata(config: OAuthConfig, fetcher: Fetch): Promise<UpstreamMetadata> {
  if (upstreamCache && upstreamCache.issuer === config.upstreamIssuer && upstreamCache.expiresAt > Date.now()) {
    return upstreamCache.value;
  }
  const response = await fetcher(`${config.upstreamIssuer}/.well-known/openid-configuration`, {
    headers: { accept: "application/json" }
  });
  if (!response.ok) throw new Error(`openTag sign-in is unavailable (discovery ${response.status})`);
  const document = (await response.json()) as Record<string, unknown>;
  if (document.issuer !== config.upstreamIssuer) throw new Error("openTag discovery issuer does not match");
  const value = {
    authorization_endpoint: String(document.authorization_endpoint || ""),
    token_endpoint: String(document.token_endpoint || ""),
    userinfo_endpoint: String(document.userinfo_endpoint || "")
  };
  if (!value.authorization_endpoint || !value.token_endpoint || !value.userinfo_endpoint) {
    throw new Error("openTag discovery is missing endpoints");
  }
  upstreamCache = { issuer: config.upstreamIssuer, value, expiresAt: Date.now() + 10 * 60 * 1000 };
  return value;
}

export function resetUpstreamCache(): void {
  upstreamCache = undefined;
}

// ---- endpoints ----

export async function register(config: OAuthConfig, request: Request): Promise<Response> {
  if (request.method !== "POST") return oauthError("invalid_request", "POST required", 405);
  let body: Record<string, unknown>;
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return oauthError("invalid_client_metadata", "Body must be JSON");
  }
  const redirectUris = body.redirect_uris;
  if (!Array.isArray(redirectUris) || redirectUris.length === 0 || redirectUris.length > 5 || !redirectUris.every(validRedirectUri)) {
    return oauthError("invalid_redirect_uri", "redirect_uris must be 1-5 https URLs (http only on localhost) without fragments");
  }
  const grantTypes = Array.isArray(body.grant_types) ? body.grant_types : ["authorization_code"];
  if (!grantTypes.every((grant) => grant === "authorization_code" || grant === "refresh_token")) {
    return oauthError("invalid_client_metadata", "Only authorization_code and refresh_token are supported");
  }
  const responseTypes = Array.isArray(body.response_types) ? body.response_types : ["code"];
  if (!responseTypes.every((type) => type === "code")) {
    return oauthError("invalid_client_metadata", "Only the code response type is supported");
  }
  const authMethod = body.token_endpoint_auth_method === "client_secret_post" ? "client_secret_post" : "client_secret_basic";
  const clientName = typeof body.client_name === "string" ? body.client_name.slice(0, 100) : undefined;
  const issuedAt = nowSeconds();
  const clientId = CLIENT_PREFIX + seal(config, "client", { ru: redirectUris, iat: issuedAt });
  return json(
    {
      client_id: clientId,
      client_secret: clientSecret(config, clientId),
      client_id_issued_at: issuedAt,
      client_secret_expires_at: 0,
      redirect_uris: redirectUris,
      grant_types: grantTypes,
      response_types: ["code"],
      token_endpoint_auth_method: authMethod,
      ...(clientName ? { client_name: clientName } : {})
    },
    201
  );
}

export async function authorize(config: OAuthConfig, request: Request, fetcher: Fetch): Promise<Response> {
  const params = new URL(request.url).searchParams;
  const client = readClient(config, params.get("client_id"));
  if (!client) return page("Unknown client.");
  const redirectUri = params.get("redirect_uri") || (client.redirectUris.length === 1 ? client.redirectUris[0] : "");
  if (!client.redirectUris.includes(redirectUri)) return page("The redirect URI is not registered for this client.");

  const state = params.get("state") || "";
  const back = (error: string, description: string) => {
    const url = new URL(redirectUri);
    url.searchParams.set("error", error);
    url.searchParams.set("error_description", description);
    if (state) url.searchParams.set("state", state);
    url.searchParams.set("iss", config.publicUrl);
    return redirect(url.toString());
  };
  if (params.get("response_type") !== "code") return back("unsupported_response_type", "Only code is supported");
  const challenge = params.get("code_challenge") || "";
  if (params.get("code_challenge_method") !== "S256" || !/^[A-Za-z0-9_-]{43,128}$/.test(challenge)) {
    return back("invalid_request", "PKCE with S256 is required");
  }
  const resource = params.get("resource") || resourceUrl(config);
  if (resource !== resourceUrl(config)) return back("invalid_target", "Unknown resource");

  let upstream: UpstreamMetadata;
  try {
    upstream = await upstreamMetadata(config, fetcher);
  } catch {
    return back("temporarily_unavailable", "openTag sign-in is unavailable");
  }
  const nonce = randomBytes(16).toString("base64url");
  const verifier = randomBytes(32).toString("base64url");
  const tx = seal(config, "tx", {
    cid: client.id,
    ru: redirectUri,
    st: state,
    cc: challenge,
    v: verifier,
    n: nonce,
    exp: nowSeconds() + TX_TTL_SECONDS
  });
  const url = new URL(upstream.authorization_endpoint);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("client_id", config.upstreamClientId);
  url.searchParams.set("redirect_uri", `${config.publicUrl}/oauth/callback`);
  url.searchParams.set("scope", "openid");
  url.searchParams.set("state", tx);
  url.searchParams.set("code_challenge", s256(verifier));
  url.searchParams.set("code_challenge_method", "S256");
  return redirect(url.toString(), {
    "set-cookie": `${TX_COOKIE}=${nonce}; Path=/oauth; Max-Age=${TX_TTL_SECONDS}; HttpOnly; Secure; SameSite=Lax`
  });
}

export async function callback(config: OAuthConfig, request: Request, fetcher: Fetch): Promise<Response> {
  const params = new URL(request.url).searchParams;
  const tx = unseal(config, "tx", params.get("state"));
  if (!tx) return page("This sign-in link has expired. Start the authorization again.");
  if (!equal(String(tx.n), cookie(request, TX_COOKIE) || "")) {
    return page("This sign-in was started in another browser. Start the authorization again in this one.");
  }
  const clearCookie = { "set-cookie": `${TX_COOKIE}=; Path=/oauth; Max-Age=0; HttpOnly; Secure; SameSite=Lax` };
  const back = (query: Record<string, string>) => {
    const url = new URL(String(tx.ru));
    for (const [name, value] of Object.entries(query)) url.searchParams.set(name, value);
    if (tx.st) url.searchParams.set("state", String(tx.st));
    url.searchParams.set("iss", config.publicUrl);
    return redirect(url.toString(), clearCookie);
  };
  if (params.get("error")) return back({ error: "access_denied", error_description: "Sign in with openTag was not completed" });
  const iss = params.get("iss");
  if (iss && iss !== config.upstreamIssuer) return back({ error: "server_error", error_description: "Unexpected issuer" });
  const code = params.get("code");
  if (!code) return back({ error: "server_error", error_description: "openTag returned no code" });

  let sub: string;
  try {
    const upstream = await upstreamMetadata(config, fetcher);
    const tokenResponse = await fetcher(upstream.token_endpoint, {
      method: "POST",
      headers: { accept: "application/json", "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "authorization_code",
        code,
        redirect_uri: `${config.publicUrl}/oauth/callback`,
        code_verifier: String(tx.v),
        client_id: config.upstreamClientId,
        client_secret: config.upstreamClientSecret
      }).toString()
    });
    if (!tokenResponse.ok) throw new Error(`token ${tokenResponse.status}`);
    const tokens = (await tokenResponse.json()) as Record<string, unknown>;
    if (typeof tokens.access_token !== "string") throw new Error("no access token");
    const userinfo = await fetcher(upstream.userinfo_endpoint, {
      headers: { accept: "application/json", authorization: `Bearer ${tokens.access_token}` }
    });
    if (!userinfo.ok) throw new Error(`userinfo ${userinfo.status}`);
    const info = (await userinfo.json()) as Record<string, unknown>;
    if (typeof info.sub !== "string" || !info.sub) throw new Error("no subject");
    sub = info.sub;
  } catch {
    return back({ error: "server_error", error_description: "Sign in with openTag failed" });
  }
  const ourCode = seal(config, "code", {
    cid: tx.cid,
    ru: tx.ru,
    cc: tx.cc,
    sub,
    exp: nowSeconds() + CODE_TTL_SECONDS
  });
  return back({ code: ourCode });
}

function issueTokens(config: OAuthConfig, sub: string, cid: string): Response {
  const now = nowSeconds();
  const aud = resourceUrl(config);
  return json({
    access_token: "mba_" + seal(config, "at", { sub, cid, aud, scope: SCOPE, exp: now + ACCESS_TTL_SECONDS }),
    token_type: "Bearer",
    expires_in: ACCESS_TTL_SECONDS,
    refresh_token: "mbr_" + seal(config, "rt", { sub, cid, aud, exp: now + REFRESH_TTL_SECONDS }),
    scope: SCOPE
  });
}

export async function token(config: OAuthConfig, request: Request): Promise<Response> {
  if (request.method !== "POST") return oauthError("invalid_request", "POST required", 405);
  const form = new URLSearchParams(await request.text());
  let clientId = form.get("client_id") || "";
  let secret = form.get("client_secret") || "";
  const header = request.headers.get("authorization") || "";
  if (header.startsWith("Basic ")) {
    const decoded = Buffer.from(header.slice(6), "base64").toString("utf8");
    const split = decoded.indexOf(":");
    if (split > 0) {
      clientId = decodeURIComponent(decoded.slice(0, split));
      secret = decodeURIComponent(decoded.slice(split + 1));
    }
  }
  const client = readClient(config, clientId);
  if (!client || !secret || !equal(secret, clientSecret(config, client.id))) {
    return oauthError("invalid_client", "Client authentication failed", 401, { "www-authenticate": "Basic" });
  }
  const resource = form.get("resource");
  if (resource && resource !== resourceUrl(config)) return oauthError("invalid_target", "Unknown resource");

  const grantType = form.get("grant_type");
  if (grantType === "authorization_code") {
    const code = unseal(config, "code", form.get("code"));
    if (!code || code.cid !== client.id) return oauthError("invalid_grant", "The code is invalid or expired");
    if (form.get("redirect_uri") && form.get("redirect_uri") !== code.ru) {
      return oauthError("invalid_grant", "redirect_uri does not match");
    }
    const verifier = form.get("code_verifier") || "";
    if (!verifier || !equal(s256(verifier), String(code.cc))) return oauthError("invalid_grant", "PKCE verification failed");
    return issueTokens(config, String(code.sub), client.id);
  }
  if (grantType === "refresh_token") {
    const refreshToken = form.get("refresh_token") || "";
    const claims = refreshToken.startsWith("mbr_") ? unseal(config, "rt", refreshToken.slice(4)) : undefined;
    if (!claims || claims.cid !== client.id || claims.aud !== resourceUrl(config)) {
      return oauthError("invalid_grant", "The refresh token is invalid or expired");
    }
    return issueTokens(config, String(claims.sub), client.id);
  }
  return oauthError("unsupported_grant_type", "Use authorization_code or refresh_token");
}

export function verifyAccessToken(config: OAuthConfig, value: string): AccessTokenClaims | undefined {
  if (!value.startsWith("mba_")) return undefined;
  const claims = unseal(config, "at", value.slice(4));
  if (!claims || claims.aud !== resourceUrl(config) || typeof claims.sub !== "string" || !claims.sub) return undefined;
  return { sub: claims.sub, cid: String(claims.cid), scope: String(claims.scope), exp: Number(claims.exp) };
}

export async function handleOAuthRequest(request: Request, op: string, fetcher: Fetch = fetch): Promise<Response> {
  const config = oauthConfigFromEnv();
  if (!config) return oauthError("temporarily_unavailable", "OAuth is not configured", 503);
  switch (op) {
    case "prm":
      return protectedResourceMetadata(config);
    case "as":
      return authorizationServerMetadata(config);
    case "register":
      return register(config, request);
    case "authorize":
      return authorize(config, request, fetcher);
    case "callback":
      return callback(config, request, fetcher);
    case "token":
      return token(config, request);
    default:
      return json({ error: "not_found" }, 404);
  }
}
