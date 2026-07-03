type AdSlotPlaceholderProps = {
  label?: string;
  className?: string;
};

export function AdSlotPlaceholder({
  label = "広告枠（AdSense 承認後に表示）",
  className,
}: AdSlotPlaceholderProps) {
  const publisherId = process.env.NEXT_PUBLIC_ADSENSE_PUBLISHER_ID?.trim();
  const slotId = process.env.NEXT_PUBLIC_ADSENSE_SLOT_HOME?.trim();

  if (publisherId && slotId) {
    return null;
  }

  return (
    <aside
      aria-label="広告プレースホルダー"
      className={`ad-placeholder ${className ?? ""}`.trim()}
    >
      <p>{label}</p>
      <small>
        環境変数 <code>NEXT_PUBLIC_ADSENSE_PUBLISHER_ID</code> と{" "}
        <code>NEXT_PUBLIC_ADSENSE_SLOT_HOME</code> を設定すると広告が表示されます。
      </small>
    </aside>
  );
}
