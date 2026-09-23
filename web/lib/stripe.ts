import Stripe from "stripe";

const ACTIVE_STATUSES = new Set(["active", "trialing"]);

export function getStripeClient(): Stripe | null {
  const key = process.env.STRIPE_SECRET_KEY?.trim();
  if (!key) {
    return null;
  }
  return new Stripe(key, {
    apiVersion: "2026-08-26.dahlia",
    typescript: true,
  });
}

export function isOwnerEmail(email: string): boolean {
  const owners = (process.env.OWNER_EMAILS ?? "")
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
  return owners.includes(email.trim().toLowerCase());
}

export function normalizeEmail(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const email = value.trim();
  if (email.length < 5 || email.length > 254) {
    return null;
  }
  const at = email.indexOf("@");
  if (at <= 0 || at !== email.lastIndexOf("@")) {
    return null;
  }
  const domain = email.slice(at + 1);
  if (!domain.includes(".")) {
    return null;
  }
  return email;
}

export async function hasActiveSubscription(
  stripe: Stripe,
  email: string,
): Promise<boolean> {
  const variants = Array.from(new Set([email, email.toLowerCase()]));
  const customerIds = new Set<string>();

  for (const variant of variants) {
    const customers = await stripe.customers.list({
      email: variant,
      limit: 10,
    });
    for (const customer of customers.data) {
      customerIds.add(customer.id);
    }
  }

  for (const customerId of customerIds) {
    const subscriptions = await stripe.subscriptions.list({
      customer: customerId,
      status: "all",
      limit: 20,
    });
    if (
      subscriptions.data.some((item) => ACTIVE_STATUSES.has(item.status))
    ) {
      return true;
    }
  }

  return false;
}
