/**
 * src/lib/api-proxy.ts
 * ====================
 * Utility helper to forward API requests from Next.js server Route Handlers
 * to the Python FastAPI backend (http://127.0.0.1:8000 by default).
 *
 * Reads the secure `admin_token` httpOnly cookie and injects it as a
 * Bearer token into the backend HTTP headers.
 */
import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://127.0.0.1:8000";

export async function proxyToBackend(
  endpoint: string,
  options: RequestInit = {}
): Promise<Response> {
  const cookieStore = await cookies();
  const token = cookieStore.get("admin_token")?.value;

  const url = `${BACKEND_URL}${endpoint}`;

  const headers = new Headers(options.headers || {});
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  try {
    const res = await fetch(url, {
      ...options,
      headers,
      cache: "no-store",
    });
    return res;
  } catch (error) {
    console.error(`Backend Proxy Error [${url}]:`, error);
    return new Response(
      JSON.stringify({
        error: true,
        message: "Failed to connect to backend service.",
        code: "BACKEND_UNREACHABLE",
      }),
      { status: 503, headers: { "Content-Type": "application/json" } }
    );
  }
}

export async function passThroughBackendResponse(backendRes: Response) {
  const data = await backendRes.json().catch(() => ({}));
  return NextResponse.json(data, { status: backendRes.status });
}
