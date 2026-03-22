import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL!;
const API_KEY = process.env.API_KEY!;

export async function POST(req: NextRequest) {
  try {
    const tokenRes = await fetch(`${BACKEND_URL}/auth/token`, {
      method: "POST",
      headers: { "X-API-Key": API_KEY },
    });

    if (!tokenRes.ok) {
      const text = await tokenRes.text();
      return NextResponse.json({ error: "Auth failed", detail: text }, { status: 502 });
    }

    const { access_token } = await tokenRes.json();

    const body = await req.json();
    const submitRes = await fetch(`${BACKEND_URL}/workflows/submit`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${access_token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    const data = await submitRes.json();
    return NextResponse.json(data, { status: submitRes.ok ? 202 : submitRes.status });
  } catch (err) {
    console.error("[/api/submit]", err);
    return NextResponse.json({ error: "Internal proxy error" }, { status: 500 });
  }
}
