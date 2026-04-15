import { NextRequest, NextResponse } from "next/server";

/**
 * Catch-all API proxy: /api/proxy/* → backend /api/*
 *
 * Eliminates CORS entirely — browser talks to same origin,
 * Next.js server calls the backend over Railway's internal network.
 */

const API_URL = process.env.API_URL || "http://localhost:8000";

// App Router: increase max duration for large file uploads
export const maxDuration = 300; // 5 minutes

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

  // Forward user identity from the auth cookie so backend endpoints can
  // resolve the current user. Cookie value is "role:displayName" — we
  // pass the displayName as-is and the backend looks up by either
  // username (lowercased) or display name.
  const authCookie = request.cookies.get("insure_auth");
  if (authCookie?.value) {
    const [role, displayName] = authCookie.value.split(":");
    if (displayName) {
      headers.set("X-User-Name", displayName);
      // Fallback — some backend endpoints might prefer lowercased username
      headers.set("X-User-Username", displayName.toLowerCase());
    }
    if (role) {
      headers.set("X-User-Role", role);
    }
  }

  const fetchOptions: RequestInit = {
    method: request.method,
    headers,
  };

  // Forward body for POST/PUT/PATCH
  if (["POST", "PUT", "PATCH"].includes(request.method)) {
    if (contentType?.includes("multipart/form-data")) {
      // Read full body for file uploads — arrayBuffer is reliable across all runtimes
      fetchOptions.body = Buffer.from(await request.arrayBuffer());
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
