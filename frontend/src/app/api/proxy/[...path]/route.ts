import { NextRequest, NextResponse } from "next/server";

/**
 * Catch-all API proxy: /api/proxy/* → backend /api/*
 *
 * Eliminates CORS entirely — browser talks to same origin,
 * Next.js server calls the backend over Railway's internal network.
 * API_URL is a runtime server-side env var, not a build-time one.
 */

const API_URL = process.env.API_URL || "http://localhost:8000";

// Disable Next.js body parsing — we stream the raw body through
export const config = {
  api: {
    bodyParser: false,
  },
};

async function proxyRequest(request: NextRequest, params: Promise<{ path: string[] }>) {
  const { path } = await params;
  const backendPath = "/api/" + path.join("/");
  const url = new URL(backendPath, API_URL);

  // Forward query params
  request.nextUrl.searchParams.forEach((value, key) => {
    url.searchParams.set(key, value);
  });

  const headers = new Headers();
  const contentType = request.headers.get("Content-Type");
  if (contentType) {
    headers.set("Content-Type", contentType);
  }
  headers.set("Accept", request.headers.get("Accept") || "application/json");

  const fetchOptions: RequestInit = {
    method: request.method,
    headers,
  };

  // Forward body for POST/PUT/PATCH — stream binary for multipart, text for JSON
  if (["POST", "PUT", "PATCH"].includes(request.method)) {
    if (contentType?.includes("multipart/form-data")) {
      // Stream the raw body through for file uploads (supports large files)
      fetchOptions.body = request.body;
      // @ts-expect-error - duplex is needed for streaming request bodies
      fetchOptions.duplex = "half";
    } else {
      fetchOptions.body = await request.text();
    }
  }

  try {
    const response = await fetch(url.toString(), fetchOptions);

    // Handle SSE streams
    if (response.headers.get("content-type")?.includes("text/event-stream")) {
      return new Response(response.body, {
        status: response.status,
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          "Connection": "keep-alive",
        },
      });
    }

    // Handle file downloads — pass through binary with all headers
    const contentDisposition = response.headers.get("content-disposition");
    const respContentType = response.headers.get("content-type") || "application/json";
    if (contentDisposition || (!respContentType.includes("json") && !respContentType.includes("text/html"))) {
      const blob = await response.arrayBuffer();
      const respHeaders: Record<string, string> = { "Content-Type": respContentType };
      if (contentDisposition) respHeaders["Content-Disposition"] = contentDisposition;
      const contentLength = response.headers.get("content-length");
      if (contentLength) respHeaders["Content-Length"] = contentLength;
      return new NextResponse(blob, { status: response.status, headers: respHeaders });
    }

    const data = await response.text();
    return new NextResponse(data, {
      status: response.status,
      headers: { "Content-Type": respContentType },
    });
  } catch (error) {
    return NextResponse.json(
      { error: "Backend unavailable", detail: String(error) },
      { status: 502 },
    );
  }
}

export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxyRequest(request, context.params);
}

export async function POST(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxyRequest(request, context.params);
}

export async function PUT(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxyRequest(request, context.params);
}

export async function DELETE(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxyRequest(request, context.params);
}
