import { AdSlotPlaceholder } from "@/components/adsense";
import { HomeAdSection } from "@/components/HomeAdSection";
import { siteConfig } from "@/lib/site";

const features = [
  {
    title: "賃貸・購入に対応",
    description:
      "アットホームの賃貸・購入情報、しずナビの購入情報を取得し、CSVとして保存できます。",
  },
  {
    title: "入居済み候補を抽出",
    description:
      "古い取得データと新しい取得データを比較し、掲載が消えた物件を入居済み候補として抽出します。",
  },
  {
    title: "半自動で運用しやすい",
    description:
      "ブラウザで検索条件を設定し、Enter を押すだけで一覧取得を開始できるローカルツールです。",
  },
];

const steps = [
  "アットホームまたはしずナビで、市区町村まで絞り込んだ一覧ページを表示する",
  "ツールで Enter を押して物件情報を CSV 保存する",
  "1か月後などに同じ条件でもう一度取得する",
  "古い CSV と新しい CSV を比較して入居済み候補を出力する",
];

const faqs = [
  {
    question: "このサイトは何をするツールですか？",
    answer:
      "不動産サイトの掲載変化を追い、掲載が消えた物件を入居済み候補として見つけるための支援ツールです。",
  },
  {
    question: "Vercel 上でスクレイピングは動きますか？",
    answer:
      "いいえ。スクレイピングと比較処理はローカル PC 上の Python アプリで実行します。このサイトは公開用のホームページです。",
  },
  {
    question: "AdSense はいつ追加できますか？",
    answer:
      "Vercel の環境変数に Publisher ID と広告スロット ID を設定すれば、承認後すぐに表示できます。",
  },
];

export default function HomePage() {
  return (
    <main className="page">
      <section className="hero">
        <span className="hero-badge">静岡県の不動産調査を効率化</span>
        <h1>{siteConfig.name}</h1>
        <p>{siteConfig.description}</p>
        <div className="hero-actions">
          <a className="button button-primary" href="#how-it-works">
            使い方を見る
          </a>
          <a className="button button-secondary" href="#faq">
            よくある質問
          </a>
        </div>
      </section>

      <section className="section-grid" aria-label="主な機能">
        {features.map((feature) => (
          <article className="card" key={feature.title}>
            <h2>{feature.title}</h2>
            <p>{feature.description}</p>
          </article>
        ))}
      </section>

      <HomeAdSection />
      <AdSlotPlaceholder />

      <section className="card" id="how-it-works">
        <h2>使い方</h2>
        <ol className="steps">
          {steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </section>

      <section className="card" id="faq">
        <h2>よくある質問</h2>
        <div className="faq-list">
          {faqs.map((item) => (
            <article className="faq-item" key={item.question}>
              <h3>{item.question}</h3>
              <p>{item.answer}</p>
            </article>
          ))}
        </div>
      </section>

      <footer className="site-footer">
        <p>
          {siteConfig.name} — ローカルツールと公開サイトを分けて運用する構成です。
        </p>
      </footer>
    </main>
  );
}
