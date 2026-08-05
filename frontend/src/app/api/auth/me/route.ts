import { passThroughBackendResponse, proxyToBackend } from "@/lib/api-proxy";

export async function GET() {
  const res = await proxyToBackend("/api/v1/auth/me");
  return passThroughBackendResponse(res);
}
