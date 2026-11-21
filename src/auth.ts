import { createRemoteJWKSet, jwtVerify, type JWTVerifyGetKey } from "jose";

/*
 * openTag Agent-mode auth (team-context personal-agent/mcp-auth-modes.md, opentag#1941).
 * openTag is the authorization server and the client; this MCP is a resource server that registers
 * nothing. It publishes Protected Resource Metadata naming openTag and verifies openTag JWTs against the
 * issuer's JWKS. The member identity is the Agent's per-resource `sub`, never a tool argument.
 *
 * TODO(opentag#1941): `opentag_auth_mode` and `opentag_subject_type` are the names in the 2026-11-21
 * design; follow the openTag implementation if it settles on different names.
 */

export const MCP_PATH = "/api/mcp";
export const AUTH_MODE = "agent";
const SUBJECT_TYPE_CLAIM = "opentag_subject_type";
/** Tokens are issued for 10 minutes; allow some clock skew but refuse anything longer-lived. */
const MAX_TOKEN_LIFETIME_SECONDS = 15 * 60;

export interface AuthConfig {
  publicUrl: string;
  issuer: string;
}

export interface AgentIdentity {
  subject: string;
  clientId?: string;
  scopes: string[];
  expiresAt: number;
}

export function authConfigFromEnv(env: NodeJS.ProcessEnv = process.env): AuthConfig | undefined {
  const publicUrl = env.MCP_PUBLIC_URL?.trim().replace(/\/+$/, "");
  const issuer = env.OPENTAG_OAUTH_ISSUER?.trim().replace(/\/+$/, "");
  if (!publicUrl || !issuer) return undefined;
  return { publicUrl, issuer };
}

export function resourceUrl(config: AuthConfig): string {
  return `${config.publicUrl}${MCP_PATH}`;
}

export function resourceMetadataUrl(config: AuthConfig): string {
  return `${config.publicUrl}/.well-known/oauth-protected-resource${MCP_PATH}`;
}

export function protectedResourceMetadata(config: AuthConfig): Response {
  return Response.json(
    {
      resource: resourceUrl(config),
      authorization_servers: [config.issuer],
      bearer_methods_supported: ["header"],
      resource_name: "薄肌教练排行榜",
      opentag_auth_mode: AUTH_MODE
    },
    { headers: { "cache-control": "public, max-age=300", "access-control-allow-origin": "*" } }
  );
}

let jwksCache: { issuer: string; keys: JWTVerifyGetKey } | undefined;

/** Resolve the issuer's JWKS from its discovery document once per process. */
async function issuerKeys(config: AuthConfig): Promise<JWTVerifyGetKey> {
  if (jwksCache?.issuer === config.issuer) return jwksCache.keys;
  const response = await fetch(`${config.issuer}/.well-known/openid-configuration`, {
    headers: { accept: "application/json" }
  });
  if (!response.ok) throw new Error(`openTag discovery failed with ${response.status}`);
  const document = (await response.json()) as Record<string, unknown>;
  if (document.issuer !== config.issuer) throw new Error("openTag discovery issuer does not match");
  if (typeof document.jwks_uri !== "string") throw new Error("openTag discovery has no jwks_uri");
  const keys = createRemoteJWKSet(new URL(document.jwks_uri));
  jwksCache = { issuer: config.issuer, keys };
  return keys;
}

export function resetIssuerKeys(): void {
  jwksCache = undefined;
}

/** Verify an openTag Agent-mode access token for this resource; undefined when it is not acceptable. */
export async function verifyAgentToken(
  config: AuthConfig,
  token: string,
  keys?: JWTVerifyGetKey
): Promise<AgentIdentity | undefined> {
  try {
    const { payload } = await jwtVerify(token, keys ?? (await issuerKeys(config)), {
      issuer: config.issuer,
      audience: resourceUrl(config),
      requiredClaims: ["sub", "exp", "iat"]
    });
    if (payload[SUBJECT_TYPE_CLAIM] !== AUTH_MODE) return undefined;
    if (typeof payload.sub !== "string" || !payload.sub) return undefined;
    if (payload.exp! - payload.iat! > MAX_TOKEN_LIFETIME_SECONDS) return undefined;
    const scope = typeof payload.scope === "string" ? payload.scope : "";
    const clientId = typeof payload.client_id === "string" ? payload.client_id : typeof payload.azp === "string" ? payload.azp : undefined;
    return { subject: `agent:${payload.sub}`, clientId, scopes: scope.split(" ").filter(Boolean), expiresAt: payload.exp! };
  } catch {
    return undefined;
  }
}
