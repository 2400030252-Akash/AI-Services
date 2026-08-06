import { passThroughBackendResponse, proxyToBackend } from "@/lib/api-proxy";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const queryString = searchParams.toString();
  const endpoint = `/api/v1/calls${queryString ? `?${queryString}` : ""}`;
  const res = await proxyToBackend(endpoint);
  return passThroughBackendResponse(res);
}
