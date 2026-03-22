import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const BACKEND_URL = process.env.BACKEND_URL!;
const API_KEY = process.env.API_KEY!;

export async function GET(
  _req: NextRequest,
  { params }: { params: { runId: string } }
) {
  try {
    const tokenRes = await fetch(`${BACKEND_URL}/auth/token`, {
      method: "POST",
      headers: { "X-API-Key": API_KEY },
      cache: "no-store",
    });

    if (!tokenRes.ok) {
      return NextResponse.json({ error: "Auth failed" }, { status: 502 });
    }

    const { access_token } = await tokenRes.json();

    const res = await fetch(`${BACKEND_URL}/workflows/${params.runId}`, {
      headers: { Authorization: `Bearer ${access_token}` },
      cache: "no-store",
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    console.error("[/api/status]", err);
    return NextResponse.json({ error: "Internal proxy error" }, { status: 500 });
  }
}
