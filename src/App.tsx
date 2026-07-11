import { useState } from "react";
import "./App.css";

type ActivityItem = {
  time: string;
  title: string;
  detail: string;
  status: "success" | "info" | "waiting";
};

const initialActivities: ActivityItem[] = [
  {
    time: "現在",
    title: "Arcを起動しました",
    detail: "新しいMissionを受け付けられます。",
    status: "success",
  },
  {
    time: "前回",
    title: "Arc Constitutionを登録",
    detail: "Arcの最上位ルールをプロジェクトへ保存しました。",
    status: "info",
  },
];

function App() {
  const [command, setCommand] = useState("");
  const [message, setMessage] = useState(
    "現在、実行中のMissionはありません。"
  );

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const trimmedCommand = command.trim();

    if (!trimmedCommand) {
      setMessage("開発したい内容を入力してください。");
      return;
    }

    setMessage(
      `Mission候補を受け付けました：「${trimmedCommand}」\n現在はUI段階のため、実行機能は次の工程で接続します。`
    );
    setCommand("");
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">A</div>
          <div>
            <div className="brand-name">Arc</div>
            <div className="brand-subtitle">専属AI開発長</div>
          </div>
        </div>

        <nav className="navigation" aria-label="メインメニュー">
          <button className="nav-item active" type="button">
            <span>⌂</span>
            司令室
          </button>
          <button className="nav-item" type="button">
            <span>◎</span>
            Mission
          </button>
          <button className="nav-item" type="button">
            <span>▦</span>
            プロジェクト
          </button>
          <button className="nav-item" type="button">
            <span>⌘</span>
            開発履歴
          </button>
          <button className="nav-item" type="button">
            <span>◇</span>
            成果物
          </button>
        </nav>

        <div className="sidebar-footer">
          <div className="owner-label">OWNER</div>
          <div className="owner-name">Master Ryuji</div>
          <div className="local-badge">ローカル環境</div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div>
            <p className="eyebrow">COMMAND CENTER</p>
            <h1>司令室</h1>
            <p className="page-description">
              目的を伝えると、Arcが設計・開発・検証をMissionとして管理します。
            </p>
          </div>

          <div className="system-status">
            <div className="status-chip">
              <span className="status-dot success" />
              Arc
            </div>
            <div className="status-chip">
              <span className="status-dot waiting" />
              AI未接続
            </div>
            <div className="status-chip">
              <span className="status-dot success" />
              Git
            </div>
          </div>
        </header>

        <section className="overview-grid">
          <article className="card mission-card">
            <div className="card-heading">
              <div>
                <p className="card-label">CURRENT MISSION</p>
                <h2>待機中</h2>
              </div>
              <span className="state-badge">READY</span>
            </div>

            <p className="mission-message">{message}</p>

            <div className="mission-stats">
              <div>
                <span>進捗</span>
                <strong>0%</strong>
              </div>
              <div>
                <span>実行中タスク</span>
                <strong>0</strong>
              </div>
              <div>
                <span>未解決エラー</span>
                <strong>0</strong>
              </div>
            </div>
          </article>

          <article className="card project-card">
            <div className="card-heading">
              <div>
                <p className="card-label">ACTIVE PROJECT</p>
                <h2>未登録</h2>
              </div>
              <span className="project-icon">PR</span>
            </div>

            <p className="muted-text">
              次の工程でProfit Radarのフォルダを登録します。
            </p>

            <div className="project-details">
              <div>
                <span>Build</span>
                <strong>未確認</strong>
              </div>
              <div>
                <span>Git</span>
                <strong>接続準備済み</strong>
              </div>
            </div>
          </article>
        </section>

        <section className="workspace-grid">
          <article className="card command-card">
            <div className="section-heading">
              <div>
                <p className="card-label">ARC COMMAND</p>
                <h2>今日は何を開発しますか？</h2>
              </div>
            </div>

            <form className="command-form" onSubmit={handleSubmit}>
              <textarea
                value={command}
                onChange={(event) => setCommand(event.target.value)}
                placeholder="例：Profit Radarの現在の問題を確認し、ベータテストに必要な作業を整理して"
                rows={5}
              />

              <div className="command-actions">
                <span>自然言語で目的を入力してください。</span>
                <button type="submit">Missionを作成</button>
              </div>
            </form>
          </article>

          <article className="card activity-card">
            <div className="section-heading">
              <div>
                <p className="card-label">ACTIVITY</p>
                <h2>開発履歴</h2>
              </div>
            </div>

            <div className="activity-list">
              {initialActivities.map((activity) => (
                <div className="activity-item" key={activity.title}>
                  <span
                    className={`activity-indicator ${activity.status}`}
                    aria-hidden="true"
                  />
                  <div className="activity-body">
                    <div className="activity-title-row">
                      <strong>{activity.title}</strong>
                      <time>{activity.time}</time>
                    </div>
                    <p>{activity.detail}</p>
                  </div>
                </div>
              ))}
            </div>
          </article>
        </section>

        <footer className="footer-note">
          Arc Desktop v0.1 — ローカル開発環境
        </footer>
      </main>
    </div>
  );
}

export default App;
