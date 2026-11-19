export default {
  fetch(): Response {
    const configured = Boolean(
      process.env.LARK_APP_ID &&
      process.env.LARK_APP_SECRET &&
      process.env.LARK_BASE_TOKEN &&
      process.env.MCP_BEARER_TOKEN
    );
    return Response.json({ service: "meiri-baoji-leaderboard", status: configured ? "ready" : "configuration_required" });
  }
};
