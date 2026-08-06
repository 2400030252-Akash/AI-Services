import { passThroughBackendResponse, proxyToBackend } from "@/lib/api-proxy";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const res = await proxyToBackend(`/api/v1/calls/${id}/conversation`);
  return passThroughBackendResponse(res);
}
