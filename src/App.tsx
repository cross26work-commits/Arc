import { useEffect, useState } from "react";
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

type CoreStatus = {
  connected: boolean;
  service: string;
  version: string;
};

type Project = {
  id: number;
  name: string;
  path: string;
  project_type: string;
  status: string;
  created_at: string;
  updated_at: string;
};

type SearchResult = {
  path: string;
  line_number: number | null;
  preview: string;
  match_type: "content" | "path";
};

type SearchResponse = {
  project_id: number;
  project_name: string;
  query: string;
  count: number;
  results: SearchResult[];
};

type IndexSummary = {
  project_id: number;
  project_name: string;
  file_count: number;
  total_lines: number;
  total_bytes: number;
  symbol_count: number;
  last_indexed_at: string | null;
  languages: Record<string, number>;
  symbol_types: Record<string, number>;
};

function App() {
  const [command, setCommand] = useState("");
  const [message, setMessage] = useState(
    "現在、実行中のMissionはありません。"
  );
  const [coreStatus, setCoreStatus] = useState<CoreStatus>({
    connected: false,
    service: "Arc Core",
    version: "-",
  });
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectError, setProjectError] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchMessage, setSearchMessage] = useState(
    "検索語を入力すると、Profit Radar内の関連コードを表示します。"
  );
  const [isSearching, setIsSearching] = useState(false);
  const [indexSummary, setIndexSummary] = useState<IndexSummary | null>(null);
  const activeProject = projects[0] ?? null;

  useEffect(() => {
    const checkCore = async () => {
      try {
        const response = await fetch("http://127.0.0.1:8765/health");

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();

        setCoreStatus({
          connected: data.status === "ok",
          service: data.service ?? "Arc Core",
          version: data.version ?? "-",
        });
      } catch {
        setCoreStatus({
          connected: false,
          service: "Arc Core",
          version: "-",
        });
      }
    };

    checkCore();

    const timer = window.setInterval(checkCore, 5000);

    const loadProjects = async () => {
      try {
        const response = await fetch("http://127.0.0.1:8765/projects");

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const data: Project[] = await response.json();
        setProjects(data);
        setProjectError("");
      } catch {
        setProjects([]);
        setProjectError("プロジェクト情報を取得できません。");
      }
    };

    loadProjects();

    const projectTimer = window.setInterval(loadProjects, 5000);

    const loadIndexSummary = async () => {
      try {
        const response = await fetch(
          "http://127.0.0.1:8765/projects/1/index/summary"
        );

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const data: IndexSummary = await response.json();
        setIndexSummary(data);
      } catch {
        setIndexSummary(null);
      }
    };

    loadIndexSummary();

    const indexTimer = window.setInterval(loadIndexSummary, 10000);

    return () => {
      window.clearInterval(timer);
      window.clearInterval(projectTimer);
      window.clearInterval(indexTimer);
    };
  }, []);

  const handleCodeSearch = async (
    event: React.FormEvent<HTMLFormElement>
  ) => {
    event.preventDefault();

    const query = searchQuery.trim();

    if (!query) {
      setSearchMessage("検索語を入力してください。");
      setSearchResults([]);
      return;
    }

    if (!activeProject) {
      setSearchMessage("検索対象のプロジェクトが登録されていません。");
      setSearchResults([]);
      return;
    }

    setIsSearching(true);
    setSearchMessage("コードを検索しています。");

    try {
      const params = new URLSearchParams({
        q: query,
        limit: "30",
      });

      const response = await fetch(
        `http://127.0.0.1:8765/projects/${activeProject.id}/search?${params}`
      );

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data: SearchResponse = await response.json();

      setSearchResults(data.results);
      setSearchMessage(
        data.count > 0
          ? `${data.count}件の関連箇所を検出しました。`
          : "該当するコードは見つかりませんでした。"
      );
    } catch {
      setSearchResults([]);
      setSearchMessage("検索に失敗しました。Arc Coreを確認してください。");
    } finally {
      setIsSearching(false);
    }
  };

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
              <span
                className={`status-dot ${
                  coreStatus.connected ? "success" : "waiting"
                }`}
              />
              {coreStatus.connected
                ? `${coreStatus.service} v${coreStatus.version}`
                : "Arc Core未接続"}
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
                <h2>{activeProject?.name ?? "未登録"}</h2>
              </div>
              <span className="project-icon">
                {activeProject?.name
                  ? activeProject.name
                      .split(" ")
                      .map((word) => word[0])
                      .join("")
                      .slice(0, 2)
                      .toUpperCase()
                  : "--"}
              </span>
            </div>

            <p className="muted-text">
              {projectError
                ? projectError
                : activeProject
                  ? activeProject.path
                  : "Arcへプロジェクトを登録してください。"}
            </p>

            <div className="project-details">
              <div>
                <span>状態</span>
                <strong>
                  {activeProject?.status === "active" ? "稼働中" : "未登録"}
                </strong>
              </div>
              <div>
                <span>登録数</span>
                <strong>{projects.length}件</strong>
              </div>
              <div>
                <span>索引ファイル</span>
                <strong>{indexSummary?.file_count ?? 0}件</strong>
              </div>
              <div>
                <span>コード行数</span>
                <strong>
                  {(indexSummary?.total_lines ?? 0).toLocaleString()}行
                </strong>
              </div>
            </div>
          </article>
        </section>

        <section className="code-search-section">
          <article className="card code-search-card">
            <div className="section-heading">
              <div>
                <p className="card-label">CODE SEARCH</p>
                <h2>Profit Radarのコードを検索</h2>
              </div>
              <span className="search-summary">
                {indexSummary
                  ? `${indexSummary.file_count}ファイル / ${indexSummary.symbol_count}シンボル`
                  : "索引未取得"}
              </span>
            </div>

            <form className="code-search-form" onSubmit={handleCodeSearch}>
              <input
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="例：返信検知、dashboard/home、company_id"
              />
              <button type="submit" disabled={isSearching}>
                {isSearching ? "検索中..." : "コード検索"}
              </button>
            </form>

            <p className="search-message">{searchMessage}</p>

            <div className="search-results">
              {searchResults.map((result, index) => (
                <div
                  className="search-result-item"
                  key={`${result.path}-${result.line_number}-${index}`}
                >
                  <div className="search-result-header">
                    <strong>{result.path}</strong>
                    <span>
                      {result.line_number
                        ? `Line ${result.line_number}`
                        : "パス一致"}
                    </span>
                  </div>
                  <code>{result.preview}</code>
                </div>
              ))}
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
