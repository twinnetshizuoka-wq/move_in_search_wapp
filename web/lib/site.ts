export const siteConfig = {
  name: "賃貸・購入物件 入居発見",
  shortName: "入居発見",
  description:
    "静岡県の賃貸・購入物件データを比較し、掲載が消えた物件を入居済み候補として抽出するツールの公式サイトです。",
  locale: "ja_JP",
  keywords: [
    "賃貸",
    "不動産",
    "入居済み",
    "静岡県",
    "物件比較",
    "アットホーム",
    "しずナビ",
  ],
} as const;

export function getSiteUrl(): string {
  const configured = process.env.NEXT_PUBLIC_SITE_URL?.trim();
  if (configured) {
    return configured.replace(/\/$/, "");
  }
  if (process.env.VERCEL_URL) {
    return `https://${process.env.VERCEL_URL}`;
  }
  return "http://localhost:3000";
}

export function getAdSensePublisherId(): string | undefined {
  const value = process.env.NEXT_PUBLIC_ADSENSE_PUBLISHER_ID?.trim();
  return value || undefined;
}
