import { ImageResponse } from "next/og";

export const size = {
  width: 180,
  height: 180,
};
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "linear-gradient(180deg, #0f6e56 0%, #0b5744 100%)",
          color: "#ffffff",
          fontSize: 72,
          fontWeight: 800,
        }}
      >
        入
      </div>
    ),
    size,
  );
}
