import { NextResponse } from "next/server";

import {
  getStripeClient,
  hasActiveSubscription,
  isOwnerEmail,
  normalizeEmail,
} from "@/lib/stripe";

export const runtime = "nodejs";

export async function GET() {
  return NextResponse.json({ ok: true });
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_json" }, { status: 400 });
  }

  const email = normalizeEmail(
    body && typeof body === "object" && "email" in body
      ? (body as { email: unknown }).email
      : null,
  );
  if (!email) {
    return NextResponse.json({ error: "invalid_email" }, { status: 400 });
  }

  if (isOwnerEmail(email)) {
    return NextResponse.json({ subscribed: true });
  }

  const stripe = getStripeClient();
  if (!stripe) {
    return NextResponse.json({ error: "not_configured" }, { status: 503 });
  }

  try {
    const subscribed = await hasActiveSubscription(stripe, email);
    return NextResponse.json({ subscribed });
  } catch {
    return NextResponse.json({ error: "lookup_failed" }, { status: 502 });
  }
}
