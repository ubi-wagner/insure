import { NextRequest, NextResponse } from "next/server";

export function middleware(request: NextRequest) {
  const authCookie = request.cookies.get("insure_auth");

  // Public routes — no auth required
  if (
    request.nextUrl.pathname.startsWith("/login") ||
    request.nextUrl.pathname.startsWith("/api/auth")
  ) {
    // If already logged in with a valid cookie, redirect to dashboard
    if (
      authCookie?.value &&
      authCookie.value.includes(":") &&
      request.nextUrl.pathname === "/login"
    ) {
      return NextResponse.redirect(new URL("/", request.url));
    }
    return NextResponse.next();
  }

  // Everything else requires auth
  if (!authCookie?.value) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  // Detect stale cookie format from before role-based auth was rolled out
  // (old cookies just had value "authenticated" with no role prefix).
  // Clear them and force re-login so the new format is set on next login.
  if (!authCookie.value.includes(":")) {
    const response = NextResponse.redirect(new URL("/login", request.url));
    response.cookies.delete("insure_auth");
    return response;
  }

  // Parse role from cookie value ("admin:Eric" or "user:Jason")
  const [role] = authCookie.value.split(":");

  // Pass role to pages via response header so client components can read it
  const response = NextResponse.next();
  response.headers.set("x-user-role", role || "user");
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
