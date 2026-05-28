import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import {
  CopilotRuntime,
  ExperimentalEmptyAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
} from "@copilotkit/runtime";
import type { AbstractAgent } from "@ag-ui/client";
import { HttpAgent } from "@ag-ui/client";

const AGENT_URL = process.env.AGENT_URL || "http://127.0.0.1:8000/api/v1/copilotkit";

const agents: Record<string, AbstractAgent> = {};
agents["default"] = new HttpAgent({ url: `${AGENT_URL}/default` });

const runtime = new CopilotRuntime({
  agents,
});

const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
  endpoint: "/api/copilotkit",
  serviceAdapter: new ExperimentalEmptyAdapter(),
  runtime,
});

export const POST = async (req: NextRequest) => {
  try {
    return await handleRequest(req);
  } catch (error: unknown) {
    console.error("[copilotkit]", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 },
    );
  }
};

export const GET = async (req: NextRequest) => {
  const url = new URL(req.url);
  
  if (url.pathname.includes('/threads')) {
    // Return 404 for threads so the frontend doesn't crash trying to iterate our healthcheck JSON
    return new Response("Not Found", { status: 404 });
  }
  
  if (url.pathname.endsWith('/api/copilotkit')) {
    // Return the custom healthcheck only on the exact base URL
    return NextResponse.json({
      status: "ok",
      agent_url: AGENT_URL,
      agent_count: Object.keys(agents).length,
    });
  }

  // Delegate other GETs (like SSE streams if any) to CopilotKit
  try {
    return await handleRequest(req);
  } catch (error: unknown) {
    console.error("[copilotkit GET]", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
};
