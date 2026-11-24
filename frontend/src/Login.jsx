import { useState } from "react";
import ThemeToggle from "./ThemeToggle.jsx";
import "./Login.css";

function Login({ onContinue, onEmailLogin, onSignup, onOAuthStart, oauthMessage = "" }) {
  const [isSignup, setIsSignup] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", password: "", confirmPassword: "" });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const handleChange = (event) => {
    const { name, value } = event.target;
    setForm((previous) => ({ ...previous, [name]: value }));
    setError("");
  };

  const handleSubmit = async (event) => {
    event.preventDefault();

    if (isSignup && !form.name.trim()) {
      setError("Enter your name to create an account.");
      return;
    }
    if (!form.email.trim() || !form.password) {
      setError("Enter your email address and password.");
      return;
    }
    if (isSignup && form.password.length < 8) {
      setError("Use at least 8 characters for your password.");
      return;
    }
    if (isSignup && form.password !== form.confirmPassword) {
      setError("Those passwords do not match.");
      return;
    }

    setBusy(true);
    setNotice("");
    try {
      if (isSignup) {
        await onSignup({ name: form.name.trim(), email: form.email.trim(), password: form.password });
        setIsSignup(false);
        setForm({ name: "", email: form.email.trim(), password: "", confirmPassword: "" });
        setNotice("Account created. Sign in with your email and password.");
      } else {
        const session = await onEmailLogin({ email: form.email.trim(), password: form.password });
        onContinue(session);
      }
    } catch (submitError) {
      setError(submitError.message || "Sign-in could not be completed. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const switchMode = () => {
    setIsSignup((previous) => !previous);
    setError("");
    setNotice("");
    setShowPassword(false);
    setForm({ name: "", email: "", password: "", confirmPassword: "" });
  };

  return (
    <div className="login-page">
      <header className="login-header">
        <a className="login-brand" href="#welcome" aria-label="NyayaLens home">
          <span className="login-brand-mark"><CourthouseIcon /></span>
          <span><strong>NyayaLens</strong><small>LEGAL DOCUMENT REVIEW</small></span>
        </a>
        <div className="login-header-right"><span>Secure sign in</span><ThemeToggle /></div>
      </header>

      <main className="login-main" id="welcome">
        <section className="login-story">
          <div className="login-eyebrow"><span /> A clearer way to review agreements</div>
          <h1>Understand the details.<br /><em>Find your footing.</em></h1>
          <p className="login-lede">Bring dense legal documents into focus with organized clauses, plain language context and preliminary review indicators.</p>
          <div className="login-benefits">
            <div><span className="benefit-check"><CheckIcon /></span><p><strong>See the structure</strong><small>Break a document into readable sections.</small></p></div>
            <div><span className="benefit-check"><CheckIcon /></span><p><strong>Spot what to review</strong><small>Surface predefined patterns for closer attention.</small></p></div>
            <div><span className="benefit-check"><CheckIcon /></span><p><strong>Stay in control</strong><small>Use the original wording to guide your next step.</small></p></div>
          </div>
          <div className="login-visual" aria-hidden="true">
            <div className="visual-document">
              <div className="visual-doc-header"><span className="visual-doc-icon"><FileIcon /></span><span><b>Service Agreement</b><small>PRELIMINARY REVIEW</small></span><span className="visual-dots">···</span></div>
              <div className="visual-rule" /><div className="visual-label">4. TERMINATION</div>
              <div className="visual-copy-line long" /><div className="visual-copy-line" />
              <div className="visual-highlight"><i /><span /><span /></div>
              <div className="visual-copy-line long" />
            </div>
            <div className="visual-note"><span className="visual-note-dot" /><span><b>Review suggested</b><small>One clause may need a closer look</small></span></div>
          </div>
          <div className="login-legal-note"><ShieldIcon /><span>Built to support understanding, not replace professional legal advice.</span></div>
        </section>

        <section className="login-card" aria-labelledby="login-title">
          <div className="login-card-heading">
            <div className="login-card-mark"><CourthouseIcon /></div>
            <div className="eyebrow">NYAYALENS WORKSPACE</div>
            <h2 id="login-title">{isSignup ? "Create your profile" : "Welcome back"}</h2>
            <p>{isSignup ? "Get started with your document review workspace." : "Sign in to continue to your workspace."}</p>
          </div>

          <form onSubmit={handleSubmit}>
            {isSignup && <div className="login-field"><label htmlFor="login-name">Full name</label><input id="login-name" type="text" name="name" value={form.name} onChange={handleChange} placeholder="Your name" autoComplete="name" required /></div>}
            <div className="login-field"><label htmlFor="login-email">Email address</label><input id="login-email" type="email" name="email" value={form.email} onChange={handleChange} placeholder="name@example.com" autoComplete="email" required /></div>
            <div className="login-field"><div className="field-label-row"><label htmlFor="login-password">Password</label>{isSignup && <span>At least 8 characters</span>}</div><div className="password-field"><input id="login-password" type={showPassword ? "text" : "password"} name="password" value={form.password} onChange={handleChange} placeholder="Enter your password" autoComplete={isSignup ? "new-password" : "current-password"} required /><button type="button" className="password-toggle" onClick={() => setShowPassword((previous) => !previous)} aria-label={showPassword ? "Hide password" : "Show password"}>{showPassword ? "Hide" : "Show"}</button></div></div>
            {isSignup && <div className="login-field"><label htmlFor="login-confirm">Confirm password</label><input id="login-confirm" type={showPassword ? "text" : "password"} name="confirmPassword" value={form.confirmPassword} onChange={handleChange} placeholder="Re-enter your password" autoComplete="new-password" required /></div>}
            {oauthMessage && <p className="login-message" role="alert">{oauthMessage}</p>}
            {notice && <p className="login-message login-success" role="status">{notice}</p>}
            {error && <p className="login-message" role="alert">{error}</p>}
            <button className="login-submit" type="submit" disabled={busy}>{busy ? "Please wait…" : isSignup ? "Create account" : "Sign in"}<span><ArrowIcon /></span></button>
          </form>

          <div className="login-switch">{isSignup ? "Already have a profile?" : "New to NyayaLens?"}<button type="button" onClick={switchMode}>{isSignup ? "Sign in" : "Create an account"}</button></div>
          <div className="login-divider"><span /> <small>OR</small> <span /></div>
          <div className="social-auth-actions">
            <button className="social-auth-button" type="button" onClick={() => onOAuthStart("github")}>Continue with GitHub</button>
            <button className="social-auth-button" type="button" onClick={() => onOAuthStart("linkedin")}>Continue with LinkedIn</button>
          </div>
          <button className="demo-link" type="button" onClick={() => onContinue({ demo: true, name: "Guest" })}>Explore the demo workspace <ArrowIcon /></button>
          <p className="login-disclaimer"><ShieldIcon /> Your password is sent only to the NyayaLens backend. Provider sign-in requires OAuth app setup.</p>
        </section>
      </main>
      <footer className="login-footer"><span>© 2026 NyayaLens</span><span>Informational assistance only</span></footer>
    </div>
  );
}

function CourthouseIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="m3 9 9-6 9 6" /><path d="M5 10h14M6 19h12M4 21h16" /><path d="M7 11v7M12 11v7M17 11v7" /></svg>;
}

function CheckIcon() {
  return <svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="m3.5 8 3 3 6-6" /></svg>;
}

function FileIcon() {
  return <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"><path d="M5 2.75h6l4 4V17a1 1 0 0 1-1 1H5a2 2 0 0 1-2-2V4.75a2 2 0 0 1 2-2Z" /><path d="M11 3v4h4M6 11h7M6 14h6" /></svg>;
}

function ShieldIcon() {
  return <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"><path d="M10 2.5 4 5v4.25c0 3.6 2.4 6.35 6 8.25 3.6-1.9 6-4.65 6-8.25V5l-6-2.5Z" /><path d="m7.5 9.8 1.7 1.7 3.4-3.5" /></svg>;
}

function ArrowIcon() {
  return <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M4 10h12M10 4l6 6-6 6" /></svg>;
}

export default Login;
