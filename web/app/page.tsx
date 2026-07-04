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
    title: "ダブルクリックで使える",
    description:
      "zip を展開して「スタート.bat」をダブルクリックするだけ。コマンド入力やプログラミング知識は不要です。",
  },
];

const steps = [
  "GitHubから「入居発見ツール.zip」をダウンロードして展開",
  "「スタート.bat」をダブルクリックしてPCで起動",
  "ブラウザでアットホーム等の物件一覧ページを開く",
  "ターミナルでEnterを押す",
  "CSVが出力される",
];

const faqs = [
  {
    question: "このサイトは何をするツールですか？",
    answer:
      "不動産サイトの掲載変化を追い、掲載が消えた物件を入居済み候補として見つけるための支援ツールです。",
  },
  {
    question: "プログラミングの知識は必要ですか？",
    answer:
      "不要です。zip をダウンロードして「スタート.bat」をダブルクリックするだけで使えます。",
  },
  {
    question: "Vercel 上でスクレイピングは動きますか？",
    answer:
      "いいえ。Playwright を使う取得処理はローカル PC 上のアプリで実行します。このサイトは公開用のホームページです。",
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
            β版を利用する
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

      <section className="card beta-section" id="beta">
        <span className="hero-badge">ローカル版として利用</span>
        <h2>β版を起動する</h2>
        <p>
          現在のβ版は、お使いの PC 上で動かすローカルツールです。ダウンロードするファイルは
          zip 1つだけで、展開後に「スタート.bat」をダブルクリックすれば使えます。Vercel
          上では Playwright を直接起動できないため、Web
          ブラウザだけで完結する版は今後対応予定です。
        </p>
        <div className="hero-actions">
          <a className="button button-primary" href="#how-it-works">
            β版を利用する
          </a>
          <a
            className="button button-secondary"
            href={siteConfig.releaseUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            zipをダウンロード
          </a>
        </div>
      </section>

      <HomeAdSection />
      <AdSlotPlaceholder />

      <section className="card" id="how-it-works">
        <h2>使い方</h2>
        <p className="section-lead">
          β版はローカル PC で起動して利用します。コマンド入力は不要です。
        </p>
        <ol className="steps">
          {steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
        <p className="notice">
          Webブラウザだけで完結する版は今後対応予定です。
        </p>
        <div className="hero-actions">
          <a
            className="button button-primary"
            href={siteConfig.releaseUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            {siteConfig.downloadZipName} をダウンロード
          </a>
          <a
            className="button button-secondary"
            href={siteConfig.githubUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            GitHubで見る
          </a>
        </div>
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
        <p>
          <a
            href={siteConfig.releaseUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            配布用 zip
          </a>
          {" / "}
          <a
            href={siteConfig.githubUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            GitHub リポジトリ
          </a>
        </p>
      </footer>
    </main>
  );
}
