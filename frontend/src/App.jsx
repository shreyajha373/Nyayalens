import { useEffect, useMemo, useRef, useState } from "react";
import Login from "./Login.jsx";
import ThemeToggle from "./ThemeToggle.jsx";
import "./App.css";

const navigation = [
  { id: "dashboard", label: "Dashboard", icon: "dashboard" },
  { id: "analyze", label: "Analyze document", icon: "analyze" },
  { id: "results", label: "Results", icon: "results" },
  { id: "history", label: "History", icon: "history" },
  { id: "settings", label: "About & settings", icon: "settings" },
];

const API_BASE_URL = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const DEMO_ANALYSIS_ENABLED = import.meta.env.VITE_ENABLE_DEMO_ANALYSIS !== "false";
const ACCESS_TOKEN_KEY = "nyayalens_access_token";
const TRANSLATION_LANGUAGES = [
  { code: "en", name: "English" },
  { code: "hi", name: "Hindi" },
  { code: "bn", name: "Bengali" },
  { code: "ta", name: "Tamil" },
  { code: "te", name: "Telugu" },
  { code: "mr", name: "Marathi" },
  { code: "es", name: "Spanish" },
  { code: "fr", name: "French" },
  { code: "de", name: "German" },
];

async function apiJson(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    throw new Error(Array.isArray(detail) ? "Check the submitted fields and try again." : detail || "The request could not be completed.");
  }
  return data;
}

function oauthErrorMessage(code) {
  const messages = {
    oauth_not_configured: "That provider is not configured yet. Add its OAuth app settings to the backend .env file.",
    email_unavailable: "The provider did not return a verified email. Verify a primary email with the provider or use email and password.",
    account_unverified: "An unverified NyayaLens account already uses this email. Complete its email verification before linking a provider.",
    account_conflict: "This provider could not be linked to the matching NyayaLens account. Contact the app owner.",
    oauth_link_conflict: "This provider account is already linked to a different NyayaLens account.",
    oauth_cancelled: "Provider sign-in was cancelled.",
    oauth_failed: "Provider sign-in could not be completed. Please try again.",
  };
  return messages[code] || messages.oauth_failed;
}

const iconShapes = {
  dashboard: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
  analyze: <><path d="M12 3v12" /><path d="m7 10 5 5 5-5" /><path d="M5 20h14" /></>,
  results: <><path d="M7 3.75h7l4 4V20a1 1 0 0 1-1 1H7a2 2 0 0 1-2-2V5.75a2 2 0 0 1 2-2Z" /><path d="M14 4v4h4M8 13h7M8 17h5" /></>,
  history: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3.5 2" /></>,
  settings: <><path d="M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z" /><path d="m19.4 15 .1.1a1.8 1.8 0 0 1-2.5 2.5l-.1-.1a1.8 1.8 0 0 0-3 .9v.2a1.8 1.8 0 0 1-3.6 0v-.2a1.8 1.8 0 0 0-3-.9l-.1.1a1.8 1.8 0 0 1-2.5-2.5l.1-.1a1.8 1.8 0 0 0-.9-3h-.2a1.8 1.8 0 0 1 0-3.6h.2a1.8 1.8 0 0 0 .9-3l-.1-.1a1.8 1.8 0 0 1 2.5-2.5l.1.1a1.8 1.8 0 0 0 3-.9v-.2a1.8 1.8 0 0 1 3.6 0v.2a1.8 1.8 0 0 0 3 .9l.1-.1a1.8 1.8 0 0 1 2.5 2.5l-.1.1a1.8 1.8 0 0 0 .9 3h.2a1.8 1.8 0 0 1 0 3.6h-.2a1.8 1.8 0 0 0-.9 3Z" /></>,
  courthouse: <><path d="m3 9 9-6 9 6" /><path d="M5 10h14M6 19h12M4 21h16" /><path d="M7 11v7M12 11v7M17 11v7" /></>,
  arrow: <><path d="M5 12h14M13 6l6 6-6 6" /></>,
  shield: <><path d="M12 3 5 6v5c0 4.5 2.8 8 7 10 4.2-2 7-5.5 7-10V6l-7-3Z" /><path d="m9 12 2 2 4-4" /></>,
  file: <><path d="M7 3.75h7l4 4V20a1 1 0 0 1-1 1H7a2 2 0 0 1-2-2V5.75a2 2 0 0 1 2-2Z" /><path d="M14 4v4h4" /></>,
};

function Icon({ name, size = 18 }) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      focusable="false"
    >
      {iconShapes[name]}
    </svg>
  );
}

function getRiskCounts(clauses = []) {
  return clauses.reduce(
    (counts, clause) => {
      const level = clause.risk_level?.toLowerCase();
      if (level === "high") counts.high += 1;
      else if (level === "medium") counts.medium += 1;
      else counts.low += 1;
      return counts;
    },
    { high: 0, medium: 0, low: 0 },
  );
}

function getItemRiskCounts(item) {
  if (Array.isArray(item?.result?.clauses)) return getRiskCounts(item.result.clauses);
  const summary = item?.result?.risk_summary || {};
  return {
    high: summary.High ?? summary.high ?? 0,
    medium: summary.Medium ?? summary.medium ?? 0,
    low: summary.Low ?? summary.low ?? 0,
  };
}

function App() {
  const [accessToken, setAccessToken] = useState(() => window.sessionStorage.getItem(ACCESS_TOKEN_KEY) || "");
  const [currentPage, setCurrentPage] = useState(() => accessToken ? "dashboard" : "login");
  const [displayName, setDisplayName] = useState("Guest");
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileInputVersion, setFileInputVersion] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [oauthMessage, setOauthMessage] = useState("");

  const currentSection = navigation.find((item) => item.id === currentPage) ?? navigation[0];
  const clauses = result?.clauses ?? [];
  const activeRiskCounts = getRiskCounts(clauses);
  const totals = useMemo(() => {
    return history.reduce(
      (counts, item) => {
        const risks = getItemRiskCounts(item);
        counts.flagged += risks.high + risks.medium;
        counts.clauses += item.result?.clause_count ?? item.result?.clauses?.length ?? 0;
        return counts;
      },
      { flagged: 0, clauses: 0 },
    );
  }, [history]);

  const openWorkspace = (session = { demo: true, name: "Guest" }) => {
    if (session.demo) {
      window.sessionStorage.removeItem(ACCESS_TOKEN_KEY);
      setAccessToken("");
      setHistory([]);
      setResult(null);
      setDisplayName(session.name || "Guest");
      setCurrentPage("dashboard");
      return;
    }
    setHistory([]);
    setResult(null);
    const token = session.access_token || "";
    if (token) {
      window.sessionStorage.setItem(ACCESS_TOKEN_KEY, token);
      setAccessToken(token);
    }
    setOauthMessage("");
    setDisplayName(session.user?.name || session.user?.email?.split("@")[0] || "NyayaLens user");
    setCurrentPage("dashboard");
  };

  const handleEmailSignup = async (details) => apiJson("/signup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(details),
  });

  const handleEmailLogin = async (details) => apiJson("/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(details),
  });

  const handleSignOut = async () => {
    if (accessToken) {
      try {
        await apiJson("/logout", {
          method: "POST",
          headers: { Authorization: `Bearer ${accessToken}` },
        });
      } catch {
        // Clear the browser session even if the API session has already expired.
      }
    }
    window.sessionStorage.removeItem(ACCESS_TOKEN_KEY);
    setAccessToken("");
    setHistory([]);
    setResult(null);
    setDisplayName("Guest");
    setCurrentPage("login");
  };

  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    const handoffCode = params.get("oauth_code");
    const providerError = params.get("oauth_error");
    if (!handoffCode && !providerError) return;

    window.history.replaceState({}, document.title, window.location.pathname);
    if (providerError) {
      setOauthMessage(oauthErrorMessage(providerError));
      setCurrentPage("login");
      return;
    }

    apiJson("/oauth/exchange", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: handoffCode }),
    }).then(openWorkspace).catch((exchangeError) => {
      setOauthMessage(exchangeError.message || "Provider sign-in could not be completed.");
      setCurrentPage("login");
    });
  }, []);

  useEffect(() => {
    if (!accessToken) return;
    let cancelled = false;
    const headers = { Authorization: `Bearer ${accessToken}` };

    apiJson("/me", { headers })
      .then((profile) => {
        if (!cancelled) setDisplayName(profile.name || profile.email?.split("@")[0] || "NyayaLens user");
      })
      .catch(() => {
        if (!cancelled) {
          window.sessionStorage.removeItem(ACCESS_TOKEN_KEY);
          setAccessToken("");
          setCurrentPage("login");
        }
      });

    apiJson("/analyses?limit=25", { headers })
      .then((data) => {
        if (!cancelled) {
          setHistory((data.items || []).map((record) => ({
            filename: record.filename,
            analyzedAt: record.created_at,
            analysisId: record.analysis_id,
            result: record,
          })));
        }
      })
      .catch(() => {});

    return () => { cancelled = true; };
  }, [accessToken]);

  const beginAnalysis = () => {
    setSelectedFile(null);
    setError("");
    setFileInputVersion((version) => version + 1);
    setCurrentPage("analyze");
  };

  const handleFileChange = (event) => {
    const file = event.target.files?.[0];
    setError("");
    setSelectedFile(null);
    if (!file) return;

    if (!/\.(pdf|txt)$/i.test(file.name)) {
      setError("Choose a PDF or TXT document to continue.");
      event.target.value = "";
      return;
    }

    setSelectedFile(file);
  };

  const handleUpload = async () => {
    if (!selectedFile) return;
    if (!accessToken && !DEMO_ANALYSIS_ENABLED) {
      setError("Sign in before uploading a document on this public website.");
      return;
    }

    setLoading(true);
    setError("");
    setResult(null);

    try {
      const formData = new FormData();
      formData.append("file", selectedFile);

      const data = await apiJson(accessToken ? "/upload" : "/demo/analyze", {
        method: "POST",
        headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
        body: formData,
      });

      setResult(data);
      setHistory((previous) => [
        {
          filename: data.filename || selectedFile.name,
          analyzedAt: data.created_at || new Date().toISOString(),
          analysisId: data.analysis_id,
          result: data,
        },
        ...previous,
      ].slice(0, 25));
      setCurrentPage("results");
    } catch (uploadError) {
      setError(
        uploadError.message === "Failed to fetch"
          ? "Cannot connect to the backend. Start FastAPI and try again."
          : uploadError.message,
      );
    } finally {
      setLoading(false);
    }
  };

  const openHistoryItem = async (item) => {
    if (item.result?.clauses || !item.analysisId) {
      setResult(item.result);
      setCurrentPage("results");
      return;
    }
    try {
      const data = await apiJson(`/analyses/${encodeURIComponent(item.analysisId)}`, {
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      setResult(data);
      setCurrentPage("results");
    } catch (openError) {
      setError(openError.message || "Could not open this saved analysis.");
      setCurrentPage("history");
    }
  };

  if (currentPage === "login") {
    return (
      <Login
        onContinue={openWorkspace}
        onEmailLogin={handleEmailLogin}
        onSignup={handleEmailSignup}
        onOAuthStart={(provider) => window.location.assign(`${API_BASE_URL}/oauth/${provider}/start`)}
        oauthMessage={oauthMessage}
      />
    );
  }

  return (
    <div className="workspace-shell">
      <aside className="sidebar">
        <button className="brand-lockup" onClick={() => setCurrentPage("dashboard")} aria-label="NyayaLens dashboard">
          <span className="brand-mark"><Icon name="courthouse" size={23} /></span>
          <span className="brand-copy"><strong>NyayaLens</strong><small>LEGAL WORKSPACE</small></span>
        </button>

        <div className="sidebar-label">WORKSPACE</div>
        <nav className="side-nav" aria-label="Main navigation">
          {navigation.map((item) => (
            <button
              className={`nav-item ${currentPage === item.id ? "is-active" : ""}`}
              key={item.id}
              onClick={() => setCurrentPage(item.id)}
              aria-current={currentPage === item.id ? "page" : undefined}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
              {item.id === "results" && result && <span className="nav-indicator" />}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="sidebar-note">
            <span className="sidebar-note-icon"><Icon name="shield" size={17} /></span>
            <p><strong>Private by design</strong><span>Documents are sent to your local analysis server.</span></p>
          </div>
          <button className="account-row" onClick={() => setCurrentPage("settings")}>
            <span className="avatar">{displayName.slice(0, 1).toUpperCase()}</span>
            <span className="account-copy"><strong>{displayName}</strong><small>{accessToken ? "Connected account" : "Demo workspace"}</small></span>
            <span className="account-chevron">···</span>
          </button>
        </div>
      </aside>

      <div className="workspace-main">
        <header className="topbar">
          <div className="breadcrumbs"><span>Workspace</span><b>/</b><strong>{currentSection.label}</strong></div>
          <div className="topbar-actions">
            <span className="preview-pill"><span /> {accessToken ? "Connected account" : "Demo mode"}</span>
            <ThemeToggle />
            <button className="topbar-avatar" onClick={() => setCurrentPage("settings")} aria-label="Open account settings">
              {displayName.slice(0, 1).toUpperCase()}
            </button>
          </div>
        </header>

        <main className="page-content">
          {currentPage === "dashboard" && (
            <Dashboard
              displayName={displayName}
              history={history}
              flaggedCount={totals.flagged}
              clauseCount={totals.clauses}
              onAnalyze={beginAnalysis}
              onViewHistory={() => setCurrentPage("history")}
              onOpenHistoryItem={(item) => { setResult(item.result); setCurrentPage("results"); }}
            />
          )}

          {currentPage === "analyze" && (
            <AnalyzeDocument
              selectedFile={selectedFile}
              inputVersion={fileInputVersion}
              error={error}
              loading={loading}
              onFileChange={handleFileChange}
              onAnalyze={handleUpload}
            />
          )}

          {currentPage === "results" && (
            <Results result={result} riskCounts={activeRiskCounts} onAnalyze={beginAnalysis} accessToken={accessToken} />
          )}

          {currentPage === "history" && (
            <History items={history} onOpen={openHistoryItem} onAnalyze={beginAnalysis} saved={Boolean(accessToken)} />
          )}

          {currentPage === "settings" && (
            <AboutSettings displayName={displayName} onSignOut={handleSignOut} />
          )}

          <footer className="page-disclaimer">
            NyayaLens provides informational assistance only. It does not replace advice from a qualified legal professional.
          </footer>
        </main>
      </div>
    </div>
  );
}

function PageHeading({ eyebrow, title, description, action }) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}

function Dashboard({ displayName, history, flaggedCount, clauseCount, onAnalyze, onViewHistory, onOpenHistoryItem }) {
  const latest = history[0];
  return (
    <>
      <PageHeading
        eyebrow="YOUR WORKSPACE"
        title={`Good to see you, ${displayName}.`}
        description="Review legal documents with a clearer view of the clauses that may need your attention."
        action={<button className="button button-primary" onClick={onAnalyze}><Icon name="analyze" size={17} /> Analyze a document</button>}
      />

      <section className="metric-grid" aria-label="Workspace overview">
        <MetricCard label="Documents analyzed" value={history.length} note="In this session" icon="results" />
        <MetricCard label="Clauses reviewed" value={clauseCount} note="Across analyzed documents" icon="file" />
        <MetricCard label="Needs attention" value={flaggedCount} note="Preliminary rule matches" icon="shield" tone="gold" />
      </section>

      <section className="dashboard-feature-grid">
        <article className="welcome-panel">
          <div className="welcome-copy">
            <div className="feature-kicker"><span className="feature-dot" /> DOCUMENT REVIEW</div>
            <h2>Make the fine print easier to navigate.</h2>
            <p>Upload a PDF or text file to extract its sections and see preliminary explanations and risk indicators.</p>
            <button className="button button-light" onClick={onAnalyze}>Start a review <Icon name="arrow" size={16} /></button>
          </div>
          <div className="document-preview" aria-hidden="true">
            <div className="preview-sheet">
              <div className="preview-sheet-top"><span /> <span /> <span /></div>
              <div className="preview-line preview-line-wide" /><div className="preview-line" />
              <div className="preview-line preview-line-short" /><div className="preview-section-title">TERMINATION</div>
              <div className="preview-highlight"><span /><span /><span /></div>
              <div className="preview-line preview-line-wide" /><div className="preview-line preview-line-short" />
            </div>
            <div className="preview-tag"><span /> Review suggested</div>
          </div>
        </article>

        <article className="panel activity-panel">
          <div className="panel-heading"><div><div className="eyebrow">RECENT ACTIVITY</div><h2>Latest reviews</h2></div><button className="text-button" onClick={onViewHistory}>View history <Icon name="arrow" size={15} /></button></div>
          {latest ? (
            <button className="activity-row" onClick={() => onOpenHistoryItem(latest)}>
              <span className="activity-file"><Icon name="file" size={18} /></span>
              <span className="activity-details"><strong>{latest.filename}</strong><small>{formatDate(latest.analyzedAt)}</small></span>
              <span className="activity-count">{latest.result?.clause_count ?? latest.result?.clauses?.length ?? 0} sections</span>
            </button>
          ) : (
            <div className="empty-activity"><span className="empty-icon"><Icon name="history" size={20} /></span><strong>No reviews yet</strong><p>Your recent document analyses will appear here.</p></div>
          )}
        </article>
      </section>

      <div className="dashboard-lower-grid">
        <article className="panel guidance-panel">
          <span className="guidance-mark"><Icon name="shield" size={20} /></span>
          <div><h3>A helpful first pass</h3><p>Risk labels are generated by predefined rules. Review the original wording and consult a legal professional before making decisions.</p></div>
        </article>
        <article className="panel workflow-panel">
          <div className="eyebrow">HOW IT WORKS</div>
          <div className="workflow-steps"><span>01 <b>Upload</b></span><i /><span>02 <b>Review</b></span><i /><span>03 <b>Understand</b></span></div>
        </article>
      </div>
    </>
  );
}

function MetricCard({ label, value, note, icon, tone }) {
  return (
    <article className={`metric-card ${tone || ""}`}>
      <div className="metric-icon"><Icon name={icon} size={19} /></div>
      <div className="metric-value">{value}</div>
      <div className="metric-label">{label}</div>
      <div className="metric-note">{note}</div>
    </article>
  );
}

function AnalyzeDocument({ selectedFile, inputVersion, error, loading, onFileChange, onAnalyze }) {
  return (
    <>
      <PageHeading eyebrow="DOCUMENT REVIEW" title="Analyze a document" description="Upload a contract or legal document to extract its sections and review potential areas of concern." />
      <section className="analyze-layout">
        <article className="panel upload-panel">
          <div className="upload-panel-heading"><span className="upload-icon"><Icon name="analyze" size={20} /></span><div><h2>Choose a document</h2><p>PDF or plain text files are supported.</p></div></div>
          <label className={`dropzone ${selectedFile ? "has-file" : ""}`} htmlFor="document-file">
            <span className="dropzone-icon"><Icon name={selectedFile ? "file" : "analyze"} size={24} /></span>
            {selectedFile ? <><strong>{selectedFile.name}</strong><span>{formatBytes(selectedFile.size)} · Ready to analyze</span></> : <><strong>Choose a file to upload</strong><span>PDF or TXT · Select from your device</span></>}
            <span className="button button-secondary">Browse files</span>
            <input key={inputVersion} id="document-file" type="file" accept=".pdf,.txt,application/pdf,text/plain" onChange={onFileChange} />
          </label>
          {error && <p className="inline-error" role="alert">{error}</p>}
          <div className="upload-actions"><button className="button button-primary" onClick={onAnalyze} disabled={!selectedFile || loading}>{loading ? <><span className="spinner" /> Analyzing document…</> : <>Analyze document <Icon name="arrow" size={16} /></>}</button><span className="upload-help">Your file is sent to the local NyayaLens backend.</span></div>
          <div className="notice-box"><Icon name="shield" size={17} /><p><strong>Informational review only.</strong> Automated labels can miss context and are not legal advice.</p></div>
        </article>
        <aside className="analyze-aside">
          <article className="panel process-panel"><div className="eyebrow">WHAT HAPPENS NEXT</div><h3>From document to clear sections</h3><ol><li><span>1</span><p><strong>Text extraction</strong><small>Read text from your PDF or TXT file.</small></p></li><li><span>2</span><p><strong>Section detection</strong><small>Group the document into readable clauses.</small></p></li><li><span>3</span><p><strong>Preliminary review</strong><small>Show rule-based flags and suggestions.</small></p></li></ol></article>
          <div className="small-note"><Icon name="shield" size={17} /><p>Only upload documents you are comfortable sending to your configured backend.</p></div>
        </aside>
      </section>
    </>
  );
}

function Results({ result, riskCounts, onAnalyze, accessToken }) {
  if (!result) {
    return <EmptyState icon="results" eyebrow="ANALYSIS RESULTS" title="Your results will appear here" description="Analyze a PDF or TXT document to see extracted sections, preliminary risk indicators and review suggestions." actionLabel="Analyze a document" onAction={onAnalyze} />;
  }

  const clauses = result.clauses ?? [];
  return (
    <>
      <PageHeading eyebrow="ANALYSIS RESULTS" title="Document review" description="A structured first pass through the document you submitted." action={<button className="button button-secondary" onClick={onAnalyze}>Analyze another</button>} />
      <section className="result-document panel"><span className="result-file-icon"><Icon name="file" size={20} /></span><div className="result-file-copy"><strong>{result.filename || "Analyzed document"}</strong><span>{result.character_count ?? 0} characters extracted · {result.clause_count ?? clauses.length} sections detected</span></div><span className="result-status"><span /> Review complete</span></section>
      <section className="result-summary-grid" aria-label="Preliminary risk summary"><RiskCard label="High concern" value={riskCounts.high} level="high" /><RiskCard label="Review suggested" value={riskCounts.medium} level="medium" /><RiskCard label="No rule matched" value={riskCounts.low} level="low" /></section>
      <section className="results-section"><div className="section-heading"><div><div className="eyebrow">CLAUSE BY CLAUSE</div><h2>Detected sections</h2></div><span className="section-count">{clauses.length} total</span></div>
        {clauses.length ? <div className="clauses-list">{clauses.map((clause, index) => <ClauseCard clause={clause} key={`${clause.heading || "section"}-${index}`} index={index} />)}</div> : <div className="panel result-empty"><p>No structured sections were returned for this document.</p></div>}
      </section>
      {result.pdf_extraction && <PdfExtractionSummary extraction={result.pdf_extraction} />}
      {result.text_preview && <details className="panel extracted-preview"><summary>View extracted text preview <span>+</span></summary><pre>{result.text_preview}</pre></details>}
      <TranslationPanel filename={result.filename} analysisId={result.analysis_id} clauses={clauses} accessToken={accessToken} />
      <p className="results-disclaimer"><Icon name="shield" size={16} /> Risk indicators are preliminary and based on predefined rules. A low or unflagged result does not mean a clause is legally safe.</p>
    </>
  );
}

function PdfExtractionSummary({ extraction }) {
  return (
    <details className="panel pdf-extraction-summary">
      <summary>PDF text by page <span>{extraction.pages_with_text} of {extraction.page_count} pages have selectable text</span></summary>
      {extraction.pages_without_text > 0 && <p className="extraction-warning" role="status">{extraction.pages_without_text} page(s) returned no selectable text. OCR is not included in this version.</p>}
      <div className="extracted-page-list">
        {(extraction.page_previews || []).map((page) => (
          <article className="extracted-page" key={page.page_number}>
            <strong>Page {page.page_number}</strong>
            <span>{page.character_count} characters</span>
            <p>{page.preview || "No selectable text was found on this page."}</p>
          </article>
        ))}
      </div>
      {extraction.previews_truncated && <p className="page-preview-note">Showing previews for the first 20 pages. The full extracted clause text remains available above.</p>}
    </details>
  );
}

function TranslationPanel({ filename, analysisId, clauses, accessToken }) {
  const [targetLanguage, setTargetLanguage] = useState("hi");
  const [sourceLanguage, setSourceLanguage] = useState("");
  const [translation, setTranslation] = useState(null);
  const [translationError, setTranslationError] = useState("");
  const [translationLoading, setTranslationLoading] = useState(false);
  const savedLookupSequence = useRef(0);

  useEffect(() => {
    setTranslation(null);
    setTranslationError("");
    if (!analysisId || !accessToken) return undefined;

    const requestSequence = ++savedLookupSequence.current;
    let cancelled = false;
    apiJson(`/analyses/${encodeURIComponent(analysisId)}/translations/${targetLanguage}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    }).then((savedTranslation) => {
      if (cancelled || savedLookupSequence.current !== requestSequence) return;
      setTranslation(savedTranslation);
      setSourceLanguage(savedTranslation.source_language === "auto" ? "" : savedTranslation.source_language);
    }).catch(() => {});

    return () => {
      cancelled = true;
      if (savedLookupSequence.current === requestSequence) savedLookupSequence.current += 1;
    };
  }, [analysisId, accessToken, targetLanguage]);

  const handleTranslate = async () => {
    if (!analysisId || !accessToken) {
      setTranslationError("Sign in and save this analysis before translating it.");
      return;
    }

    setTranslationLoading(true);
    setTranslationError("");
    try {
      const data = await apiJson(`/analyses/${encodeURIComponent(analysisId)}/translations`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${accessToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          target_language: targetLanguage,
          source_language: sourceLanguage || null,
        }),
      });
      setTranslation(data);
    } catch (error) {
      setTranslationError(error.message || "The clauses could not be translated.");
    } finally {
      setTranslationLoading(false);
    }
  };

  const detectedNames = (translation?.detected_source_languages || [])
    .map((code) => TRANSLATION_LANGUAGES.find((language) => language.code === code)?.name || code);

  const handleSaveAsPdf = () => {
    if (!translation) return;

    const printWindow = window.open("", "_blank", "width=900,height=700");
    if (!printWindow) {
      setTranslationError("Allow pop-ups for NyayaLens, then try saving the PDF again.");
      return;
    }
    printWindow.opener = null;

    const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\"": "&quot;",
      "'": "&#39;",
    })[character]);
    const displayName = translation.target_language_name || targetLanguage;
    const baseName = (filename || "NyayaLens document").replace(/\.[^.]+$/, "");
    const documentTitle = `${baseName} - ${displayName} translation`;
    const translatedContent = (translation.translated_clauses || []).map((item, index) => {
      const original = clauses[index] || {};
      const translatedHeading = item.translated_heading || `Clause ${item.clause_number || index + 1}`;
      return `
        <section class="clause">
          <h2>${escapeHtml(translatedHeading)}</h2>
          <p class="translated">${escapeHtml(item.translated_text).replace(/\r?\n/g, "<br>")}</p>
          <h3>Original · ${escapeHtml(original.heading || `Clause ${index + 1}`)}</h3>
          <p class="original">${escapeHtml(original.text).replace(/\r?\n/g, "<br>")}</p>
        </section>`;
    }).join("");

    const targetCode = escapeHtml(translation.target_language || targetLanguage);
    printWindow.document.open();
    printWindow.document.write(`<!doctype html>
      <html lang="${targetCode}">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>${escapeHtml(documentTitle)}</title>
          <style>
            @page { size: A4; margin: 18mm 16mm; }
            * { box-sizing: border-box; }
            body { margin: 0; color: #17212b; font: 11pt/1.65 "Nirmala UI", "Noto Sans", "Noto Sans Devanagari", "Noto Sans Bengali", "Noto Sans Tamil", "Noto Sans Telugu", "Segoe UI", sans-serif; }
            header { margin-bottom: 18pt; padding-bottom: 12pt; border-bottom: 1px solid #c7d0d8; }
            h1 { margin: 0 0 5pt; font: 22pt/1.2 Georgia, "Times New Roman", serif; }
            .subtitle { margin: 0; color: #526170; }
            .clause { margin: 0 0 18pt; break-inside: auto; }
            h2 { margin: 0 0 6pt; font-size: 13pt; line-height: 1.4; break-after: avoid; }
            p { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
            h3 { margin: 13pt 0 4pt; color: #526170; font-size: 9pt; font-weight: 600; break-after: avoid; }
            .original { color: #526170; font-size: 9pt; }
            footer { margin-top: 24pt; padding-top: 9pt; border-top: 1px solid #c7d0d8; color: #526170; font-size: 8.5pt; }
            @media screen { body { max-width: 800px; margin: 32px auto; padding: 0 28px; } }
          </style>
        </head>
        <body>
          <header><h1>${escapeHtml(documentTitle)}</h1><p class="subtitle">Translated clauses with the original text for comparison.</p></header>
          ${translatedContent}
          <footer>Machine translation is for understanding only. Legal wording can lose nuance. Compare with the source document; this is not legal advice.</footer>
        </body>
      </html>`);
    printWindow.document.close();
    printWindow.focus();
    window.setTimeout(() => printWindow.print(), 400);
    setTranslationError("");
  };

  return (
    <section className="panel translation-panel">
      <div className="translation-heading">
        <div className="eyebrow">MULTILINGUAL VIEW</div>
        <h2>Translate source clauses</h2>
        <p>The original clause and analyzer results remain unchanged. Translation is saved separately for this analysis.</p>
        <p className="translation-limit-note">The existing rule-based risk detector still uses English-language patterns.</p>
      </div>
      <div className="translation-controls">
        <label className="translation-field" htmlFor="source-language">
          <span>Source language</span>
          <select id="source-language" value={sourceLanguage} disabled={translationLoading} onChange={(event) => {
            savedLookupSequence.current += 1;
            const nextSourceLanguage = event.target.value;
            setSourceLanguage(nextSourceLanguage);
            setTranslation(null);
            if (nextSourceLanguage && nextSourceLanguage === targetLanguage) {
              setTargetLanguage(TRANSLATION_LANGUAGES.find((language) => language.code !== nextSourceLanguage).code);
            }
          }}>
            <option value="">Auto-detect</option>
            {TRANSLATION_LANGUAGES.map((language) => <option key={language.code} value={language.code}>{language.name}</option>)}
          </select>
        </label>
        <label className="translation-field" htmlFor="target-language">
          <span>Translate to</span>
          <select id="target-language" value={targetLanguage} disabled={translationLoading} onChange={(event) => { setTargetLanguage(event.target.value); setTranslation(null); }}>
            {TRANSLATION_LANGUAGES.map((language) => <option key={language.code} value={language.code} disabled={language.code === sourceLanguage}>{language.name}</option>)}
          </select>
        </label>
        <button className="button button-primary" onClick={handleTranslate} disabled={translationLoading || !analysisId || !accessToken || !clauses.length}>
          {translationLoading ? <><span className="spinner" /> Translating…</> : translation ? "Load saved translation" : "Translate clauses"}
        </button>
      </div>
      {translationError && <p className="inline-error" role="alert">{translationError}</p>}
      {translation && (
        <>
          <p className="translation-status" role="status">
            Saved translation: {translation.target_language_name || targetLanguage}
            {detectedNames.length > 0 && !sourceLanguage ? ` · Source detected as ${detectedNames.join(", ")}` : ""}
          </p>
          <div className="translation-results">
            {(translation.translated_clauses || []).map((translatedClause, index) => {
              const originalClause = clauses[index] || {};
              return (
                <article className="translation-pair" key={`${translatedClause.clause_number}-${index}`}>
                  <div className="translation-column">
                    <span>Original · {originalClause.heading || `Clause ${index + 1}`}</span>
                    <p>{originalClause.text}</p>
                  </div>
                  <div className="translation-column translated-column">
                    <span>{translation.target_language_name || targetLanguage}{translatedClause.translated_heading ? ` · ${translatedClause.translated_heading}` : ""}</span>
                    <p>{translatedClause.translated_text}</p>
                  </div>
                </article>
              );
            })}
          </div>
          <div className="translation-export-actions">
            <button className="button button-secondary" type="button" onClick={handleSaveAsPdf}>Print / Save as PDF</button>
            <span>In the print window, choose “Save as PDF”.</span>
          </div>
          <p className="translation-disclaimer">Machine translation is for understanding only. Legal wording can lose nuance; compare the source and consult a qualified legal professional.</p>
        </>
      )}
    </section>
  );
}

function RiskCard({ label, value, level }) {
  return <article className={`risk-summary-card risk-${level}`}><span className="risk-dot" /><div><strong>{value}</strong><span>{label}</span></div></article>;
}

function ClauseCard({ clause, index }) {
  const level = clause.risk_level?.toLowerCase() || "unknown";
  return (
    <details className="clause-card" open={index === 0}>
      <summary><span className="clause-title"><span className="clause-index">{String(index + 1).padStart(2, "0")}</span><strong>{clause.heading || `Section ${index + 1}`}</strong></span><span className={`risk-badge risk-${level}`}>{clause.risk_level || "Not analyzed"}</span></summary>
      <div className="clause-body"><p className="clause-text">{clause.text}</p><div className="risk-analysis"><div className="risk-analysis-label">PRELIMINARY REVIEW · {clause.risk_level || "Not analyzed"}</div>{clause.detected_concerns?.length ? clause.detected_concerns.map((concern, concernIndex) => <div className="detected-concern" key={concernIndex}><span className={`risk-badge risk-${concern.risk_level?.toLowerCase() || "unknown"}`}>{concern.risk_level || "Review"}</span><p><strong>Why it was flagged</strong>{concern.reason}</p><p><strong>Suggested next step</strong>{concern.suggestion}</p></div>) : <p className="no-concerns">No predefined concern was detected in this section. This does not necessarily mean the clause is legally safe.</p>}</div></div>
    </details>
  );
}

function History({ items, onOpen, onAnalyze, saved }) {
  return (
    <>
      <PageHeading eyebrow="YOUR DOCUMENTS" title="Analysis history" description={saved ? "Revisit documents saved to your account." : "Sign in to analyze documents and save their history to an account."} action={<button className="button button-primary" onClick={onAnalyze}><Icon name="analyze" size={17} /> New analysis</button>} />
      {items.length ? <section className="panel history-panel"><div className="history-header"><span>DOCUMENT</span><span>SECTIONS</span><span>REVIEWED</span><span /></div>{items.map((item, index) => <button className="history-row" key={`${item.analyzedAt}-${index}`} onClick={() => onOpen(item)}><span className="history-document"><span className="activity-file"><Icon name="file" size={18} /></span><span><strong>{item.filename}</strong><small>PDF / text document</small></span></span><span className="history-sections">{item.result?.clause_count ?? item.result?.clauses?.length ?? 0}</span><span className="history-date">{formatDate(item.analyzedAt)}</span><span className="history-open"><Icon name="arrow" size={17} /></span></button>)}</section> : <EmptyState icon="history" eyebrow="YOUR DOCUMENTS" title="No documents in your history yet" description={saved ? "Once you analyze a document, it will appear here." : "Sign in to analyze and save your document history."} actionLabel="Analyze a document" onAction={onAnalyze} />}
      {saved && <p className="history-note">Signed-in analyses are saved to your NyayaLens account so you can return to them later.</p>}
    </>
  );
}

function AboutSettings({ displayName, onSignOut }) {
  return (
    <>
      <PageHeading eyebrow="PREFERENCES" title="About & settings" description="Learn about NyayaLens and adjust your workspace preferences." />
      <section className="settings-grid">
        <article className="panel about-card"><span className="about-mark"><Icon name="courthouse" size={27} /></span><div className="eyebrow">ABOUT NYAYALENS</div><h2>Legal documents, made clearer.</h2><p>NyayaLens is a legal document analysis prototype designed to help people navigate dense agreements. It extracts sections, provides plain language context and highlights predefined patterns for review.</p><div className="about-facts"><div><span>Current workspace</span><strong>{displayName}</strong></div><div><span>Analysis method</span><strong>Preliminary, rule-based review</strong></div><div><span>Session history</span><strong>Stored temporarily in this browser</strong></div></div></article>
        <div className="settings-side"><article className="panel preference-card"><div className="eyebrow">APPEARANCE</div><h3>Color theme</h3><p>Choose the theme that feels comfortable for your workspace.</p><div className="theme-setting-row"><span><strong>Display theme</strong><small>Switch between light and dark mode</small></span><ThemeToggle /></div></article><article className="panel account-settings"><div className="eyebrow">ACCOUNT</div><h3>Signed-in workspace</h3><p>Your uploads and analysis history are associated with this account.</p><button className="button button-secondary" onClick={onSignOut}>Sign out</button></article></div>
      </section>
    </>
  );
}

function EmptyState({ icon, eyebrow, title, description, actionLabel, onAction }) {
  return <section className="panel empty-state"><span className="empty-state-icon"><Icon name={icon} size={24} /></span><div className="eyebrow">{eyebrow}</div><h2>{title}</h2><p>{description}</p><button className="button button-primary" onClick={onAction}>{actionLabel} <Icon name="arrow" size={16} /></button></section>;
}

function formatDate(value) {
  if (!value) return "Just now";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function formatBytes(bytes = 0) {
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default App;
