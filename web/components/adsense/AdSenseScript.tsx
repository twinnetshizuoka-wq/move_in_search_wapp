import Script from "next/script";

import { getAdSensePublisherId } from "@/lib/site";

type AdSenseScriptProps = {
  publisherId?: string;
};

export function AdSenseScript({ publisherId }: AdSenseScriptProps) {
  const resolvedPublisherId = publisherId ?? getAdSensePublisherId();

  if (!resolvedPublisherId) {
    return null;
  }

  return (
    <Script
      id="adsense-script"
      async
      src={`https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${resolvedPublisherId}`}
      crossOrigin="anonymous"
      strategy="afterInteractive"
    />
  );
}
