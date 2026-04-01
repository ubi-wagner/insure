import { NextResponse } from "next/server";

/**
 * Serve the Google Maps API key at runtime.
 * This avoids needing NEXT_PUBLIC_ build-time env vars.
 */
export async function GET() {
  const key = process.env.GOOGLE_MAPS_KEY || process.env.NEXT_PUBLIC_GOOGLE_MAPS_KEY || process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY || "";
  return NextResponse.json({ key });
}
