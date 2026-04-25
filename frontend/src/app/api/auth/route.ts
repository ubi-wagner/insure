import { NextRequest, NextResponse } from "next/server";

/**
 * Users and roles.
 *
 * admin:  full access — seed, refresh, recalibrate, upload, download, query, reset DB
 * user:   pipeline + card review — can add contacts, move stages, record
 *         engagements, upload lead documents, but CANNOT run admin actions
 * viewer: strictly read-only — can view dashboard, ops, files, lead details, but
 *         CANNOT change stages, add contacts, upload, send outreach, or run admin actions
 */
export type UserRole = "admin" | "user" | "viewer";

const USERS: Record<string, { password: string; role: UserRole; displayName: string }> = {
  eric: { password: "eric123", role: "admin", displayName: "Eric" },
  jason: { password: "jason123", role: "user", displayName: "Jason" },
  demo: { password: "demo123", role: "viewer", displayName: "Demo" },
};

export async function POST(request: NextRequest) {
  const body = await request.json();
  const { username, password } = body;

  const user = USERS[username?.toLowerCase()];
  if (user && user.password === password) {
    // Cookie value encodes role + display name so middleware and pages can
    // check without a DB round-trip.  Format: "role:displayName"
    const cookieValue = `${user.role}:${user.displayName}`;
    const response = NextResponse.json({
      success: true,
      role: user.role,
      displayName: user.displayName,
    });
    response.cookies.set("insure_auth", cookieValue, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      maxAge: 60 * 60 * 24 * 7, // 7 days
      path: "/",
    });
    return response;
  }

  return NextResponse.json(
    { success: false, error: "Invalid credentials" },
    { status: 401 }
  );
}

export async function GET(request: NextRequest) {
  /** Return current user info from the cookie (no DB round-trip). */
  const authCookie = request.cookies.get("insure_auth");
  if (!authCookie?.value) {
    return NextResponse.json({ authenticated: false }, { status: 401 });
  }
  const [role, displayName] = authCookie.value.split(":");
  return NextResponse.json({
    authenticated: true,
    role: (role as UserRole) || "user",
    displayName: displayName || "Unknown",
  });
}

export async function DELETE() {
  const response = NextResponse.json({ success: true });
  response.cookies.delete("insure_auth");
  return response;
}
