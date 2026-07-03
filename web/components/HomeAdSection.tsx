import { AdSlot } from "@/components/adsense";

const homeAdSlot = process.env.NEXT_PUBLIC_ADSENSE_SLOT_HOME?.trim();

export function HomeAdSection() {
  if (!homeAdSlot) {
    return null;
  }

  return (
    <section className="ad-section" aria-label="広告">
      <AdSlot slotId={homeAdSlot} format="auto" className="home-ad-slot" />
    </section>
  );
}
