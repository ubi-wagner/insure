import { NextRequest, NextResponse } from "next/server";

export function middleware(request: NextRequest) {
  const authCookie = request.cookies.get("insure_auth");

  if (
    !authCookie &&
    !request.nextUrl.pathname.startsWith("/login") &&
    !request.nextUrl.pathname.startsWith("/api/auth")
  ) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  if (authCookie && request.nextUrl.pathname === "/login") {
    return NextResponse.redirect(new URL("/", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
