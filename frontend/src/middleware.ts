import { NextRequest, NextResponse } from "next/server";

export function middleware(request: NextRequest) {
  const authCookie = request.cookies.get("insure_auth");

  // Public routes — no auth required
  if (
    request.nextUrl.pathname.startsWith("/login") ||
    request.nextUrl.pathname.startsWith("/api/auth")
  ) {
    // If already logged in and hitting /login, redirect to dashboard
    if (authCookie && request.nextUrl.pathname === "/login") {
      return NextResponse.redirect(new URL("/", request.url));
    }
    return NextResponse.next();
  }

  // Everything else requires auth
  if (!authCookie?.value) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  // Parse role from cookie value ("admin:Eric" or "user:Jason")
  const [role] = authCookie.value.split(":");

  // Pass role to pages via response header so client components can read it.
  // Also set it as a cookie-readable value for client-side checks.
  const response = NextResponse.next();
  response.headers.set("x-user-role", role || "user");
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
