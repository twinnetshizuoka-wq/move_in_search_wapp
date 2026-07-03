import { ImageResponse } from "next/og";

import { siteConfig } from "@/lib/site";

export const runtime = "edge";
export const alt = siteConfig.name;
export const size = {
  width: 1200,
  height: 630,
};
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "64px",
          background: "linear-gradient(135deg, #0f6e56 0%, #123f68 100%)",
          color: "#ffffff",
          fontFamily: "Segoe UI, sans-serif",
        }}
      >
        <div
          style={{
            fontSize: 28,
            fontWeight: 700,
            opacity: 0.9,
          }}
        >
          Rental Discovery
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div style={{ fontSize: 64, fontWeight: 800, lineHeight: 1.1 }}>
            {siteConfig.name}
          </div>
          <div style={{ fontSize: 30, lineHeight: 1.5, maxWidth: 900, opacity: 0.92 }}>
            {siteConfig.description}
          </div>
        </div>
      </div>
    ),
    size,
  );
}
