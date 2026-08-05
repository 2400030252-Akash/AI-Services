import { passThroughBackendResponse, proxyToBackend } from "@/lib/api-proxy";

export async function GET() {
  const res = await proxyToBackend("/api/v1/dashboard/summary");
  return passThroughBackendResponse(res);
}
