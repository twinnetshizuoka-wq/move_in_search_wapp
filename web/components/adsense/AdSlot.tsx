"use client";

import { useEffect } from "react";

import { getAdSensePublisherId } from "@/lib/site";

declare global {
  interface Window {
    adsbygoogle?: Record<string, unknown>[];
  }
}

type AdSlotProps = {
  slotId: string;
  format?: "auto" | "rectangle" | "horizontal" | "vertical";
  className?: string;
  testMode?: boolean;
};

export function AdSlot({
  slotId,
  format = "auto",
  className,
  testMode = false,
}: AdSlotProps) {
  const publisherId = getAdSensePublisherId();

  useEffect(() => {
    if (!publisherId || !slotId || testMode) {
      return;
    }

    try {
      (window.adsbygoogle = window.adsbygoogle || []).push({});
    } catch {
      // AdSense is optional until publisher approval is complete.
    }
  }, [publisherId, slotId, testMode]);

  if (!publisherId || !slotId) {
    return null;
  }

  return (
    <ins
      className={`adsbygoogle block ${className ?? ""}`.trim()}
      data-ad-client={publisherId}
      data-ad-slot={slotId}
      data-ad-format={format}
      data-full-width-responsive="true"
      data-adtest={testMode ? "on" : undefined}
    />
  );
}
