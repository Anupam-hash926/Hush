import "./styles.css";

const app = document.querySelector("#app");
const TOKEN_KEY = "hush_access_token";
const EMAIL_KEY = "hush_user_email";
const THEME_KEY = "hush_theme";

const state = {
  token: localStorage.getItem(TOKEN_KEY),
  email: localStorage.getItem(EMAIL_KEY) || "",
  route: localStorage.getItem(TOKEN_KEY) ? "app" : "home",
  authMode: "login",
  theme: localStorage.getItem(THEME_KEY) === "dark" ? "dark" : "light",
  projects: [],
  selectedProjectId: "",
  section: "overview",
  secrets: {},
  secretStatuses: {},
  approvers: {},
  inbox: [],
  vaultLoading: false,
  inboxLoading: false,
  modal: null,
  drawerOpen: false,
  toast: null,
};

document.documentElement.dataset.theme = state.theme;

const escapeHtml = (value = "") =>
  String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);

const selectedProject = () =>
  state.projects.find((project) => project.id === state.selectedProjectId);

const projectRoleLabel = (project) => {
  if (!project) return "";
  if (project.access_type === "OWNS") return "Owner";
  if (project.role) {
    return project.role.charAt(0).toUpperCase() + project.role.slice(1);
  }
  return "Shared";
};

function notify(message, type = "success") {
  state.toast = { message, type };
  render();
  window.setTimeout(() => {
    state.toast = null;
    render();
  }, 3600);
}

function clearSession(route = "home") {
  state.token = "";
  state.email = "";
  state.projects = [];
  state.selectedProjectId = "";
  state.secrets = {};
  state.secretStatuses = {};
  state.approvers = {};
  state.inbox = [];
  state.route = route;
  if (route === "auth") state.authMode = "login";
  state.drawerOpen = false;
  state.modal = null;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(EMAIL_KEY);
  render();
}

function setTheme(theme) {
  state.theme = theme;
  document.documentElement.dataset.theme = theme;
  localStorage.setItem(THEME_KEY, theme);
  render();
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.token) headers.set("Authorization", `Bearer ${state.token}`);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  let response;
  try {
    response = await fetch(`/api${path}`, { ...options, headers });
  } catch {
    throw new Error("Could not reach Hush API. Check that the backend is running on port 8000.");
  }

  const contentType = response.headers.get("content-type") || "";
  const result = contentType.includes("application/json") ? await response.json() : null;

  if (!response.ok) {
    const detail = result?.detail;
    const message = typeof detail === "string" ? detail : `Request failed (${response.status}).`;
    if (response.status === 401 && state.token) {
      clearSession("auth");
    }
    const err = new Error(message);
    err.status = response.status;
    throw err;
  }

  return result;
}

async function loadProjects() {
  try {
    const result = await api("/projects");
    state.projects = result.projects || [];
  } catch (error) {
    if (error.message.includes("No projects found")) {
      state.projects = [];
    } else {
      throw error;
    }
  }
  if (!state.projects.some((project) => project.id === state.selectedProjectId)) {
    state.selectedProjectId = state.projects[0]?.id || "";
  }
}

async function loadVault(projectId) {
  if (!projectId) return;
  state.vaultLoading = true;
  render();

  try {
    let secretsList = [];
    try {
      const result = await api(`/projects/${encodeURIComponent(projectId)}/secrets`);
      secretsList = result.secrets || [];
    } catch (error) {
      if (error.status === 404) {
        secretsList = [];
      } else {
        throw error;
      }
    }
    state.secrets[projectId] = secretsList;

    await Promise.all(
      secretsList.map(async (secret) => {
        const existing = state.secretStatuses[secret.id] || {};
        const reqQuery = existing.request_id
          ? `?request_id=${encodeURIComponent(existing.request_id)}`
          : "";
        try {
          const statusData = await api(
            `/projects/${encodeURIComponent(projectId)}/secrets/${encodeURIComponent(secret.id)}/request-status${reqQuery}`
          );
          state.secretStatuses[secret.id] = {
            ...statusData,
            access_token: statusData.status === "claimed" ? existing.access_token || null : null,
          };
        } catch {
          state.secretStatuses[secret.id] = { status: "none" };
        }

        try {
          const approverData = await api(
            `/projects/${encodeURIComponent(projectId)}/secrets/${encodeURIComponent(secret.id)}/approvers`
          );
          state.approvers[secret.id] = approverData.eligible_approvers || [];
        } catch {
          state.approvers[secret.id] = [];
        }
      })
    );
  } catch (error) {
    notify(error.message, "error");
  } finally {
    state.vaultLoading = false;
    render();
  }
}

async function loadInbox() {
  state.inboxLoading = true;
  render();
  try {
    const result = await api("/approvals/inbox");
    state.inbox = result.inbox || [];
  } catch (error) {
    notify(error.message, "error");
  } finally {
    state.inboxLoading = false;
    render();
  }
}

function logo() {
  return `<span class="brand-mark" aria-hidden="true"><span></span><span></span><span></span></span>`;
}

function renderHome() {
  app.innerHTML = `
    <main class="home-page">
      <header class="home-nav">
        <a class="brand" href="#" data-action="home">${logo()}<span>hush</span></a>
        <nav class="home-nav-links" aria-label="Main navigation">
          <a href="#how-it-works">How it works</a>
          <a href="#principles">Our approach</a>
        </nav>
        <div class="home-nav-actions">
          <button type="button" class="theme-button" data-action="toggle-theme" aria-label="Switch to ${state.theme === "light" ? "dark" : "light"} mode">${state.theme === "light" ? "Dark mode" : "Light mode"}</button>
          <button type="button" class="button button-secondary home-signin" data-action="open-auth" data-mode="login">Sign in</button>
          <button type="button" class="button button-primary" data-action="open-auth" data-mode="register">Create account</button>
        </div>
      </header>
      <section class="home-hero">
        <div class="home-hero-copy">
          <p class="eyebrow"><span class="hero-status"></span> A calmer way to handle sensitive work</p>
          <h1>Keep your secrets<br />close. Your team,<br /><span>in the loop.</span></h1>
          <p class="home-lede">Hush gives your team one clear place to organize project credentials and share access with intention.</p>
          <div class="home-hero-actions"><button type="button" class="button button-primary button-large" data-action="open-auth" data-mode="register">Get started <span aria-hidden="true">→</span></button><button type="button" class="text-button home-text-button" data-action="open-auth" data-mode="login">I already have an account</button></div>
          <div class="home-proof"><span class="lock-icon" aria-hidden="true"></span><span>Private project spaces</span><span class="proof-divider"></span><span>Access on your terms</span></div>
        </div>
        <div class="home-hero-visual" aria-label="Illustration of a protected project workspace">
          <div class="visual-backdrop"></div>
          <div class="visual-window">
            <div class="visual-window-top"><span class="visual-brand-mark">${logo()}</span><span>Workspace</span><span class="visual-avatar">A</span></div>
            <div class="visual-layout">
              <div class="visual-sidebar"><span class="visual-side-item selected"></span><span class="visual-side-item"></span><span class="visual-side-item"></span><span class="visual-side-item"></span></div>
              <div class="visual-content"><div class="visual-label">PRIVATE PROJECT</div><div class="visual-title">Product launch</div><div class="visual-description">Credentials for your team</div>
                <div class="visual-secret"><span class="visual-key">K</span><div><strong>Production API key</strong><small>Revealed only when approved</small></div><span class="visual-hidden">••••••••••</span></div>
                <div class="visual-access"><span class="visual-access-mark">✓</span><div><strong>Shared with care</strong><small>Quorum-gated access</small></div></div>
              </div>
            </div>
          </div>
          <div class="visual-note"><span class="visual-note-mark"><span></span></span><span><strong>Private by default</strong><small>Claim when approved</small></span></div>
        </div>
      </section>
      <section class="home-principles" id="principles">
        <div class="principle-intro"><p class="eyebrow">A little more peace of mind</p><h2>Sensitive work,<br />without the noise.</h2><p>Less hunting through messages. More clarity around who can access what.</p></div>
        <article class="principle-card"><span class="principle-number">01</span><div class="principle-icon">${icon("folder")}</div><h3>One space per project</h3><p>Keep credentials organized alongside the work and people they belong to.</p></article>
        <article class="principle-card"><span class="principle-number">02</span><div class="principle-icon">${icon("key")}</div><h3>Quorum-gated access</h3><p>Secret values stay encrypted until approvers sign off and you claim a one-time token.</p></article>
        <article class="principle-card"><span class="principle-number">03</span><div class="principle-icon">${icon("users")}</div><h3>Share with intention</h3><p>Invite teammates with clear roles and review pending requests from your inbox.</p></article>
      </section>
      <section class="home-how" id="how-it-works"><div><p class="eyebrow">GETTING STARTED</p><h2>Simple from the<br />very first project.</h2></div><div class="how-steps"><div class="how-step"><span>1</span><div><h3>Create your space</h3><p>Start a project for a team, service, or initiative.</p></div></div><div class="how-step"><span>2</span><div><h3>Add what matters</h3><p>Store sensitive values with quorum and view limits.</p></div></div><div class="how-step"><span>3</span><div><h3>Bring in your team</h3><p>Share the project and approve requests from your inbox.</p></div></div></div></section>
      <footer class="home-footer"><a class="brand" href="#" data-action="home">${logo()}<span>hush</span></a><span>Private by design. Clear by default.</span><button type="button" class="text-button" data-action="open-auth" data-mode="register">Start with Hush <span aria-hidden="true">→</span></button></footer>
    </main>
    ${toastMarkup()}`;
}

function renderAuth(mode = state.authMode, error = "") {
  state.route = "auth";
  state.authMode = mode;
  const isRegister = mode === "register";
  app.innerHTML = `
    <main class="auth-page">
      <section class="auth-brand-panel">
        <a class="brand" href="#" data-action="home" aria-label="Hush home">${logo()}<span>hush</span></a>
        <div class="auth-message">
          <p class="eyebrow">${isRegister ? "A more considered workspace" : "Your work, just as you left it"}</p>
          <h1>${isRegister ? "Give sensitive work<br />a space of its own." : "Good to have you<br />back in the loop."}</h1>
          <p>${isRegister ? "Create a private home for project credentials and invite your team when you're ready." : "Your projects, shared access, and secrets are waiting in one calm workspace."}</p>
        </div>
        <div class="auth-footnote"><span class="status-dot"></span> Thoughtful access. Clear project spaces.</div>
      </section>
      <section class="auth-form-panel">
        <div class="auth-form-wrap">
          <div class="auth-topline"><a href="#" class="mobile-brand brand" data-action="home">${logo()}<span>hush</span></a><button type="button" class="theme-button auth-theme-button" data-action="toggle-theme">${state.theme === "light" ? "Dark mode" : "Light mode"}</button></div>
          <button type="button" class="auth-back-link" data-action="home">← <span>Back to home</span></button>
          <p class="eyebrow">${isRegister ? "GET STARTED" : "WELCOME BACK"}</p>
          <h2>${isRegister ? "Create your account" : "Sign in to Hush"}</h2>
          <p class="form-intro">${isRegister ? "It only takes a moment to set up." : "Enter your details to continue to your workspace."}</p>
          ${error ? `<div class="alert alert-error" role="alert">${escapeHtml(error)}</div>` : ""}
          <form id="auth-form" data-mode="${isRegister ? "register" : "login"}">
            <label for="email">Email or username</label>
            <input id="email" name="email" type="text" autocomplete="username" placeholder="name@company.com" required />
            <div class="password-label-row"><label for="password">Password</label></div>
            <input id="password" name="password" type="password" autocomplete="${isRegister ? "new-password" : "current-password"}" placeholder="${isRegister ? "Create a password" : "Enter your password"}" required />
            <button class="button button-primary button-wide auth-submit" type="submit">${isRegister ? "Create account" : "Continue"}<span aria-hidden="true">→</span></button>
          </form>
          <div class="auth-divider"><span>or</span></div>
          <p class="auth-switch">${isRegister ? "Already have an account?" : "New to Hush?"} <button type="button" class="text-button" data-action="switch-auth" data-mode="${isRegister ? "login" : "register"}">${isRegister ? "Sign in" : "Create an account"}</button></p>
          <p class="auth-security"><span class="lock-icon" aria-hidden="true"></span>Private project spaces, protected with secure authentication.</p>
        </div>
      </section>
    </main>
    ${toastMarkup()}`;
}

function toastMarkup() {
  if (!state.toast) return "";
  return `<div class="toast toast-${state.toast.type}" role="status">${escapeHtml(state.toast.message)}</div>`;
}

const navItems = [
  { id: "overview", label: "Overview", icon: "grid" },
  { id: "projects", label: "Projects", icon: "folder" },
  { id: "vault", label: "Secret vault", icon: "key" },
  { id: "access", label: "Shared access", icon: "users" },
];

function icon(name) {
  const paths = {
    grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    folder: '<path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h5l2 2h8A1.5 1.5 0 0 1 21 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z"/>',
    key: '<circle cx="8" cy="15" r="4"/><path d="m11 12 8-8 2 2-2 2 2 2-3 3-2-2-3 3"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="10" cy="7" r="4"/><path d="M20 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
  };
  return `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]}</svg>`;
}

function renderShell() {
  if (!state.token) {
    if (state.route === "auth") renderAuth();
    else renderHome();
    return;
  }

  const title = navItems.find((item) => item.id === state.section)?.label || "Overview";
  app.innerHTML = `
    <div class="app-shell">
      <aside class="sidebar">
        <a class="brand sidebar-brand" href="#" aria-label="Hush home">${logo()}<span>hush</span></a>
        <div class="workspace-label">WORKSPACE</div>
        <nav class="primary-nav" aria-label="Main navigation">
          ${navItems.map((item) => `
            <button type="button" class="nav-item ${state.section === item.id ? "active" : ""}" data-action="navigate" data-section="${item.id}">
              ${icon(item.icon)}<span>${item.label}</span>
            </button>`).join("")}
        </nav>
        <div class="sidebar-bottom">
          <div class="sidebar-note">
            <span class="note-icon" aria-hidden="true">i</span>
            <div><strong>Quorum by default</strong><p>Secrets stay encrypted until approved and claimed.</p></div>
          </div>
          <button type="button" class="profile-button" data-action="open-drawer" aria-label="Open profile and settings">
            <span class="avatar">${escapeHtml((state.email[0] || "H").toUpperCase())}</span>
            <span class="profile-copy"><strong>${escapeHtml(state.email)}</strong><small>Profile & settings</small></span>
            <span class="profile-menu" aria-hidden="true">···</span>
          </button>
        </div>
      </aside>
      <main class="main-panel">
        <header class="topbar">
          <div class="breadcrumbs"><span>Workspace</span><span class="crumb-divider">/</span><strong>${title}</strong></div>
          <div class="topbar-right"><span class="api-indicator"><span class="status-dot"></span> API connected</span><button type="button" class="theme-button topbar-theme" data-action="toggle-theme">${state.theme === "light" ? "Dark mode" : "Light mode"}</button><button type="button" class="topbar-avatar" data-action="open-drawer" aria-label="Open profile and settings">${escapeHtml((state.email[0] || "H").toUpperCase())}</button></div>
        </header>
        <section class="page-content page-transition">${renderPage()}</section>
      </main>
    </div>
    ${state.drawerOpen ? renderDrawer() : ""}
    ${state.modal ? renderModal() : ""}
    ${toastMarkup()}`;
}

function renderDrawer() {
  return `<div class="drawer-backdrop" data-action="close-drawer">
    <aside class="settings-drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
      <div class="drawer-header"><div><p class="eyebrow">YOUR ACCOUNT</p><h2 id="drawer-title">Profile & settings</h2></div><button type="button" class="icon-button" data-action="close-drawer" aria-label="Close settings">×</button></div>
      <div class="drawer-profile"><span class="drawer-avatar">${escapeHtml((state.email[0] || "H").toUpperCase())}</span><div><strong>${escapeHtml(state.email)}</strong><small>Hush account</small></div></div>
      <section class="drawer-section"><p class="drawer-section-label">APPEARANCE</p><div class="drawer-setting"><div><strong>Display mode</strong><small>Choose the look that works for you.</small></div><button type="button" class="theme-switch ${state.theme === "dark" ? "is-on" : ""}" data-action="toggle-theme" aria-label="Switch to ${state.theme === "light" ? "dark" : "light"} mode" aria-pressed="${state.theme === "dark"}"><span></span></button></div><div class="drawer-mode-label">${state.theme === "light" ? "Bright mode" : "Dark mode"}<span>Saved on this device</span></div></section>
      <section class="drawer-section"><p class="drawer-section-label">WORKSPACE</p><button class="drawer-link" type="button" data-action="drawer-navigate" data-section="overview">${icon("grid")}<span>Overview</span></button><button class="drawer-link" type="button" data-action="drawer-navigate" data-section="projects">${icon("folder")}<span>Projects</span></button><button class="drawer-link" type="button" data-action="drawer-navigate" data-section="access">${icon("users")}<span>Shared access</span></button></section>
      <section class="drawer-help"><strong>Need a hand?</strong><p>Hush keeps sensitive values encrypted until quorum is met and claimed.</p><button type="button" class="link-button" data-action="drawer-help">About Hush <span aria-hidden="true">→</span></button></section>
      <div class="drawer-footer"><button type="button" class="drawer-signout" data-action="confirm-sign-out"><span class="signout-icon" aria-hidden="true">↗</span> Sign out</button></div>
    </aside>
  </div>`;
}

function pageHeader(eyebrow, title, description, action = "") {
  return `<div class="page-heading"><div><p class="eyebrow">${eyebrow}</p><h1>${title}</h1><p class="page-description">${description}</p></div>${action}</div>`;
}

function projectCard(project, compact = false) {
  const owned = project.access_type === "OWNS";
  return `<article class="project-card ${compact ? "project-card-compact" : ""}">
    <div class="project-card-top"><span class="project-symbol">${escapeHtml(project.name.charAt(0).toUpperCase() || "P")}</span><span class="access-badge ${owned ? "badge-owner" : "badge-shared"}">${escapeHtml(projectRoleLabel(project))}</span></div>
    <h3>${escapeHtml(project.name)}</h3>
    <p>${escapeHtml(project.description || "A private space for project credentials and shared access.")}</p>
    <div class="project-card-bottom"><span>${state.secrets[project.id]?.length ?? "—"} secrets</span><button type="button" class="link-button" data-action="open-project" data-project-id="${escapeHtml(project.id)}">Open vault <span aria-hidden="true">→</span></button></div>
  </article>`;
}

function renderOverview() {
  const projects = state.projects;
  const preview = projects.slice(0, 3);
  return `
    ${pageHeader("YOUR WORKSPACE", `Good to see you, ${escapeHtml(state.email.split("@")[0])}.`, "A clear view of your projects and shared secrets.", `<button class="button button-primary" type="button" data-action="new-project"><span aria-hidden="true">＋</span> New project</button>`)}
    <div class="welcome-banner">
      <div><p class="eyebrow">Private by design</p><h2>Keep sensitive work<br />in the right hands.</h2><p>Create a project, add a secret, and require quorum approval before anyone can decrypt it.</p><button class="button button-light" type="button" data-action="navigate" data-section="vault">Open your vault <span aria-hidden="true">→</span></button></div>
      <div class="welcome-art" aria-hidden="true"><div class="art-frame"><div class="art-lock"><span></span></div><div class="art-line art-line-long"></div><div class="art-line"></div><div class="art-line art-line-short"></div><span class="art-dot"></span></div><span class="art-caption">PRIVATE<br />PROJECT SPACE</span></div>
    </div>
    <div class="section-heading"><div><h2>Your projects</h2><p>${projects.length ? `${projects.length} ${projects.length === 1 ? "project" : "projects"} in your workspace` : "Start with a dedicated space for your team."}</p></div><button class="link-button" type="button" data-action="navigate" data-section="projects">View all <span aria-hidden="true">→</span></button></div>
    ${projects.length ? `<div class="project-grid">${preview.map((project) => projectCard(project, true)).join("")}</div>` : `<div class="empty-state"><div class="empty-symbol">${icon("folder")}</div><h3>Your workspace starts here</h3><p>Create a project to organize secrets and share access with your team.</p><button type="button" class="button button-secondary" data-action="new-project">Create your first project</button></div>`}
    <div class="info-strip"><span class="info-mark" aria-hidden="true">i</span><p><strong>Approvals inbox is live.</strong> Review pending secret requests across projects where you are an owner, editor, or reviewer.</p><button class="link-button" type="button" data-action="navigate" data-section="access">Open inbox <span aria-hidden="true">→</span></button></div>`;
}

function renderProjects() {
  return `
    ${pageHeader("ORGANIZE", "Projects", "Keep each team's secrets and access in one focused space.", `<button class="button button-primary" type="button" data-action="new-project"><span aria-hidden="true">＋</span> New project</button>`)}
    ${state.projects.length ? `<div class="project-grid project-grid-full">${state.projects.map((project) => projectCard(project)).join("")}</div>` : `<div class="empty-state"><div class="empty-symbol">${icon("folder")}</div><h3>No projects yet</h3><p>Create your first project, then add a secret or share access with a teammate.</p><button type="button" class="button button-primary" data-action="new-project">Create a project</button></div>`}`;
}

function projectSelect() {
  if (!state.projects.length) return `<div class="empty-state compact-empty"><div class="empty-symbol">${icon("folder")}</div><h3>No project selected</h3><p>Create a project before managing secrets.</p><button class="button button-secondary" type="button" data-action="new-project">Create a project</button></div>`;
  return `<div class="project-picker"><label for="project-select">Project</label><select id="project-select">${state.projects.map((project) => `<option value="${escapeHtml(project.id)}" ${project.id === state.selectedProjectId ? "selected" : ""}>${escapeHtml(project.name)}</option>`).join("")}</select><span class="select-chevron" aria-hidden="true">⌄</span></div>`;
}

function renderSecretAction(secret) {
  const st = state.secretStatuses[secret.id] || { status: "none" };
  const status = st.status || "none";

  if (status === "pending") {
    const live = st.current_live_approvals ?? 0;
    const quorum = st.quorum_size ?? secret.quorum_size;
    return `<span class="access-badge badge-shared">Pending · ${live}/${quorum} approvals</span>`;
  }
  if (status === "approved") {
    return `<button type="button" class="button button-primary" data-action="claim-access" data-secret-id="${escapeHtml(secret.id)}">Claim access</button>`;
  }
  if (status === "claimed") {
    if (st.access_token) {
      return `<button type="button" class="button button-primary" data-action="view-secret" data-secret-id="${escapeHtml(secret.id)}">View secret</button>`;
    }
    return `<span class="access-badge badge-owner">Claimed</span>`;
  }

  const label =
    status === "expired"
      ? "Expired — Request again"
      : status === "rejected"
      ? "Rejected — Request again"
      : status === "revoked"
      ? "Revoked — Request again"
      : "Request access";

  return `<button type="button" class="button button-secondary" data-action="request-access" data-secret-id="${escapeHtml(secret.id)}">${label}</button>`;
}

function renderVault() {
  const project = selectedProject();
  const owned = project?.access_type === "OWNS";
  const secrets = state.secrets[project?.id] || null;
  const controls = project
    ? `<div class="vault-actions">
        <button class="button button-secondary" type="button" data-action="refresh-vault">Refresh</button>
        <button class="button button-primary" type="button" data-action="new-secret">＋ Add secret</button>
      </div>`
    : "";

  let content = "";
  if (!project) {
    content = `<div class="empty-state"><div class="empty-symbol">${icon("key")}</div><h3>Choose a project to continue</h3><p>Secrets belong to a project, so you can keep access organized.</p></div>`;
  } else if (state.vaultLoading && secrets === null) {
    content = `<div class="empty-state"><div class="empty-symbol">${icon("key")}</div><h3>Loading vault…</h3><p>Fetching secret metadata and live request status.</p></div>`;
  } else if (!secrets || !secrets.length) {
    content = `<div class="empty-state"><div class="empty-symbol">${icon("key")}</div><h3>No secrets in this project</h3><p>Add a credential or sensitive value to get started.</p><button class="button button-primary" type="button" data-action="new-secret">Add the first secret</button></div>`;
  } else {
    content = `<div class="secret-list">${secrets.map((secret) => {
      const approvers = state.approvers[secret.id] || [];
      const approverLine = approvers.length
        ? ` · Approvers: ${approvers.map(escapeHtml).join(", ")}`
        : "";
      return `
      <article class="secret-row">
        <div class="secret-key-icon">${icon("key")}</div>
        <div class="secret-main">
          <h3>${escapeHtml(secret.key_name)}</h3>
          <p class="secret-value">Quorum: ${secret.quorum_size} · Window: ${secret.access_window_hours}h · Max views: ${secret.max_views}${approverLine}</p>
        </div>
        <div class="secret-meta" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
          ${renderSecretAction(secret)}
          ${owned ? `<button type="button" class="link-button" data-action="open-audit" data-secret-id="${escapeHtml(secret.id)}" data-secret-name="${escapeHtml(secret.key_name)}">Audit</button>` : ""}
          ${owned ? `<button type="button" class="link-button" data-action="open-revoke" data-secret-id="${escapeHtml(secret.id)}" data-secret-name="${escapeHtml(secret.key_name)}">Revoke</button>` : ""}
        </div>
      </article>`;
    }).join("")}</div>`;
  }

  return `
    ${pageHeader("SENSITIVE VALUES", "Secret vault", "Metadata only. Request access, collect quorum approvals, and claim a one-time token to decrypt.", controls)}
    <div class="vault-toolbar">${projectSelect()}${project ? `<span class="vault-project-caption"><span class="status-dot"></span> ${escapeHtml(project.name)} · ${escapeHtml(projectRoleLabel(project))}</span>` : ""}</div>
    ${project ? content : ""}
    ${project ? `<p class="vault-footnote"><span class="lock-icon" aria-hidden="true"></span>Plaintext is never returned in vault listings. Access tokens live in memory only and burn after max views.</p>` : ""}`;
}

function renderAccess() {
  const inboxHtml = state.inboxLoading
    ? `<p class="form-intro">Loading pending requests…</p>`
    : !state.inbox.length
    ? `<div class="inline-empty"><p>No pending requests waiting on your approval.</p></div>`
    : `<div class="secret-list">${state.inbox.map((item) => {
        const ownsProject = state.projects.some(
          (p) => p.id === item.project_id && p.access_type === "OWNS"
        );
        return `
        <article class="secret-row" style="display:flex;flex-direction:column;align-items:flex-start;gap:10px;">
          <div class="secret-main">
            <h3>${escapeHtml(item.key_name)} <small style="font-weight:400;opacity:0.75;">in ${escapeHtml(item.project_name)}</small></h3>
            <p class="secret-value">Requested by <strong>${escapeHtml(item.requester_email)}</strong> · ${item.live_approvals}/${item.quorum_size} live approvals</p>
          </div>
          <div class="button-row" style="align-items:center;gap:8px;">
            <select data-validity-for="${escapeHtml(item.request_id)}" aria-label="Approval validity" style="width:auto;padding:6px 10px;">
              <option value="3600">Valid 1h</option>
              <option value="86400" selected>Valid 24h</option>
              <option value="604800">Valid 7d</option>
            </select>
            <button type="button" class="button button-primary" data-action="inbox-approve" data-project-id="${escapeHtml(item.project_id)}" data-secret-id="${escapeHtml(item.secret_id)}" data-request-id="${escapeHtml(item.request_id)}" data-target-email="${escapeHtml(item.requester_email)}">Approve</button>
            <button type="button" class="button button-secondary button-danger" data-action="inbox-reject" data-project-id="${escapeHtml(item.project_id)}" data-secret-id="${escapeHtml(item.secret_id)}" data-request-id="${escapeHtml(item.request_id)}" data-target-email="${escapeHtml(item.requester_email)}">Reject</button>
            ${ownsProject ? `<button type="button" class="link-button" data-action="inbox-revoke" data-project-id="${escapeHtml(item.project_id)}" data-secret-id="${escapeHtml(item.secret_id)}" data-request-id="${escapeHtml(item.request_id)}" data-target-email="${escapeHtml(item.requester_email)}">Revoke</button>` : ""}
          </div>
        </article>`;
      }).join("")}</div>`;

  return `
    ${pageHeader("TEAM PERMISSIONS", "Shared access", "Invite teammates to a project or review pending requests in your inbox.")}
    <div class="access-layout">
      <section class="content-card">
        <div class="card-heading"><span class="card-icon">${icon("users")}</span><div><h2>Share a project</h2><p>Give a teammate access to the selected project.</p></div></div>
        ${state.projects.length ? `<form data-form="share-project" class="stack-form">
          <label for="share-project-select">Project</label><select id="share-project-select" name="project_id" required>${state.projects.map((project) => `<option value="${escapeHtml(project.id)}" ${project.id === state.selectedProjectId ? "selected" : ""}>${escapeHtml(project.name)}</option>`).join("")}</select>
          <label for="share-email">Teammate's email or username</label><input id="share-email" name="target_email" type="text" placeholder="teammate@company.com" required />
          <label for="share-role">Permission</label><select id="share-role" name="role"><option value="viewer">Viewer — can request secret access</option><option value="editor">Editor — can add secrets and approve requests</option></select>
          <button class="button button-primary" type="submit">Share project <span aria-hidden="true">→</span></button>
        </form>` : `<div class="inline-empty"><p>Create a project before you can share it.</p><button class="button button-secondary" type="button" data-action="new-project">Create project</button></div>`}
      </section>
      <section class="content-card approval-card">
        <div class="card-heading" style="justify-content:space-between;width:100%;">
          <div style="display:flex;align-items:center;gap:12px;"><span class="card-icon approval-icon">${icon("key")}</span><div><h2>Approvals inbox</h2><p>Pending requests across your projects.</p></div></div>
          <button type="button" class="button button-secondary" data-action="refresh-inbox">Refresh</button>
        </div>
        ${inboxHtml}
      </section>
    </div>
    <section class="member-section"><div class="section-heading"><div><h2>Project access</h2><p>Projects available in your workspace.</p></div><button type="button" class="link-button" data-action="navigate" data-section="projects">Manage projects <span aria-hidden="true">→</span></button></div>
      ${state.projects.length ? `<div class="access-project-list">${state.projects.map((project) => `<div class="access-project"><span class="project-symbol small-symbol">${escapeHtml(project.name.charAt(0).toUpperCase() || "P")}</span><div><strong>${escapeHtml(project.name)}</strong><small>${escapeHtml(projectRoleLabel(project))}</small></div><button type="button" class="link-button" data-action="select-project" data-project-id="${escapeHtml(project.id)}">Open vault <span aria-hidden="true">→</span></button></div>`).join("")}</div>` : ""}
    </section>`;
}

function renderPage() {
  switch (state.section) {
    case "projects": return renderProjects();
    case "vault": return renderVault();
    case "access": return renderAccess();
    default: return renderOverview();
  }
}

function renderModal() {
  const modal = state.modal;
  if (!modal) return "";
  let title = "";
  let content = "";

  if (modal.kind === "project") {
    title = "Create a project";
    content = `<p class="modal-intro">Give your team a clear, private space to work.</p><form data-form="create-project" class="stack-form"><label for="project-name">Project name</label><input id="project-name" name="name" placeholder="e.g. Product launch" required maxlength="80" /><label for="project-description">Description <span class="optional">(optional)</span></label><textarea id="project-description" name="description" rows="3" placeholder="What is this project for?"></textarea><div class="modal-actions"><button class="button button-secondary" type="button" data-action="close-modal">Cancel</button><button class="button button-primary" type="submit">Create project</button></div></form>`;
  } else if (modal.kind === "secret") {
    title = "Add a secret";
    content = `<p class="modal-intro">Add a value to <strong>${escapeHtml(selectedProject()?.name || "this project")}</strong>. Access requires quorum approval.</p><form data-form="create-secret" class="stack-form"><label for="secret-name">Secret name</label><input id="secret-name" name="key_name" placeholder="e.g. Production API key" required maxlength="100" /><label for="secret-value">Secret value</label><textarea id="secret-value" name="secret_value" rows="4" placeholder="Paste the sensitive value" required></textarea><div class="form-two-col"><div><label for="quorum">Approvals required</label><input id="quorum" name="quorum_size" type="number" min="1" value="1" required /></div><div><label for="window-hours">Access window (hours)</label><input id="window-hours" name="access_window_hours" type="number" min="1" value="24" required /></div></div><label for="max-views">Max views per token</label><input id="max-views" name="max_views" type="number" min="1" value="1" required /><div class="notice notice-soft"><span class="lock-icon" aria-hidden="true"></span><p>Values are encrypted with AES-256-GCM by the backend.</p></div><div class="modal-actions"><button class="button button-secondary" type="button" data-action="close-modal">Cancel</button><button class="button button-primary" type="submit">Save secret</button></div></form>`;
  } else if (modal.kind === "view-secret") {
    title = modal.secretName || "Decrypted secret";
    content = `<p class="modal-intro">Views remaining after this read: <strong>${modal.viewsRemaining}</strong></p><label for="decrypted-value">Secret value</label><div class="token-field"><input id="decrypted-value" value="${escapeHtml(modal.secretValue)}" readonly /><button type="button" class="button button-secondary" data-action="copy-secret">Copy</button></div><p class="modal-footnote">${modal.viewsRemaining === 0 ? "This token has been burned and removed from memory." : "Close this dialog when done."}</p><div class="modal-actions"><button class="button button-primary" type="button" data-action="close-modal">Done</button></div>`;
  } else if (modal.kind === "audit") {
    title = `Audit log · ${escapeHtml(modal.secretName)}`;
    const rows = modal.logs || [];
    content = !rows.length
      ? `<p class="modal-intro">No audit events recorded for this secret yet.</p><div class="modal-actions"><button class="button button-primary" type="button" data-action="close-modal">Close</button></div>`
      : `<div style="max-height:360px;overflow:auto;"><table style="width:100%;border-collapse:collapse;font-size:0.85rem;">
          <thead><tr style="text-align:left;border-bottom:1px solid var(--border, #ddd);"><th style="padding:6px;">Time</th><th style="padding:6px;">Actor</th><th style="padding:6px;">Type</th><th style="padding:6px;">Target</th><th style="padding:6px;">Outcome</th></tr></thead>
          <tbody>${rows.map((log) => `<tr style="border-bottom:1px solid var(--border, #eee);"><td style="padding:6px;white-space:nowrap;">${escapeHtml((log.timestamp || "").replace("T", " ").slice(0, 19))}</td><td style="padding:6px;">${escapeHtml(log.actor)}</td><td style="padding:6px;">${escapeHtml(log.type)}</td><td style="padding:6px;">${escapeHtml(log.target || "—")}</td><td style="padding:6px;">${escapeHtml(log.outcome)}${log.reason ? ` (${escapeHtml(log.reason)})` : ""}</td></tr>`).join("")}</tbody>
        </table></div><div class="modal-actions" style="margin-top:16px;"><button class="button button-primary" type="button" data-action="close-modal">Close</button></div>`;
  } else if (modal.kind === "revoke") {
    title = `Revoke access · ${escapeHtml(modal.secretName)}`;
    content = `<p class="modal-intro">Immediately terminate any active token or pending request for a user on this secret.</p><form data-form="revoke-secret" class="stack-form"><input type="hidden" name="secret_id" value="${escapeHtml(modal.secretId)}" /><label for="revoke-email">Target user email or username</label><input id="revoke-email" name="target_email" type="text" placeholder="anirudh" required /><div class="modal-actions"><button class="button button-secondary" type="button" data-action="close-modal">Cancel</button><button class="button button-primary" type="submit">Revoke access</button></div></form>`;
  } else if (modal.kind === "sign-out") {
    title = "Sign out of Hush?";
    content = `<p class="modal-intro">You can sign back in any time. Any unclaimed or in-memory access tokens on this device will be cleared.</p><div class="modal-actions"><button class="button button-secondary" type="button" data-action="close-modal">Stay signed in</button><button class="button button-primary" type="button" data-action="confirm-sign-out-now">Sign out</button></div>`;
  } else if (modal.kind === "about") {
    title = "About Hush";
    content = `<p class="modal-intro">Hush is a multi-model secret vault built on FastAPI, Neo4j, and Redis with quorum-gated access.</p><div class="notice notice-soft"><span class="lock-icon" aria-hidden="true"></span><p>Secrets stay encrypted at rest and require live quorum approvals before a one-time token can be claimed.</p></div><div class="modal-actions"><button class="button button-primary" type="button" data-action="close-modal">Got it</button></div>`;
  }

  return `<div class="modal-backdrop" data-action="backdrop-close"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><div class="modal-heading"><h2 id="modal-title">${title}</h2><button class="icon-button" type="button" data-action="close-modal" aria-label="Close dialog">×</button></div>${content}</section></div>`;
}

function render() {
  renderShell();
}

async function authenticate(form) {
  const data = new FormData(form);
  const email = String(data.get("email")).trim();
  const password = String(data.get("password"));
  const mode = form.dataset.mode;
  try {
    if (mode === "register") {
      await api("/register", { method: "POST", body: JSON.stringify({ email, password }) });
    }
    const result = await api("/login", { method: "POST", body: JSON.stringify({ email, password }) });
    state.token = result.access_token;
    state.email = email;
    localStorage.setItem(TOKEN_KEY, state.token);
    localStorage.setItem(EMAIL_KEY, email);
    await loadProjects();
    state.route = "app";
    state.drawerOpen = false;
    state.section = "overview";
    render();
  } catch (error) {
    renderAuth(mode, error.message);
  }
}

async function submitProject(form) {
  const data = new FormData(form);
  try {
    const result = await api("/projects", {
      method: "POST",
      body: JSON.stringify({ name: data.get("name"), description: data.get("description") || null }),
    });
    state.modal = null;
    await loadProjects();
    state.selectedProjectId = result.project.id;
    state.section = "vault";
    await loadVault(state.selectedProjectId);
    notify("Project created.");
  } catch (error) {
    notify(error.message, "error");
  }
}

async function submitSecret(form) {
  const project = selectedProject();
  if (!project) return;
  const data = new FormData(form);
  try {
    await api(`/projects/${encodeURIComponent(project.id)}/secrets`, {
      method: "POST",
      body: JSON.stringify({
        key_name: data.get("key_name"),
        secret_value: data.get("secret_value"),
        quorum_size: Number(data.get("quorum_size")),
        access_window_hours: Number(data.get("access_window_hours")),
        max_views: Number(data.get("max_views") || 1),
      }),
    });
    state.modal = null;
    await loadVault(project.id);
    notify("Secret saved.");
  } catch (error) {
    notify(error.message, "error");
  }
}

async function submitShare(form) {
  const data = new FormData(form);
  try {
    await api(`/projects/${encodeURIComponent(data.get("project_id"))}/share`, {
      method: "POST",
      body: JSON.stringify({ target_email: data.get("target_email"), role: data.get("role") }),
    });
    form.reset();
    notify("Project access granted.");
  } catch (error) {
    notify(error.message, "error");
  }
}

async function submitRevoke(form) {
  const project = selectedProject();
  if (!project) return;
  const data = new FormData(form);
  const secretId = String(data.get("secret_id"));
  const targetEmail = String(data.get("target_email")).trim();
  try {
    await api(`/projects/${encodeURIComponent(project.id)}/secrets/${encodeURIComponent(secretId)}/revoke`, {
      method: "POST",
      body: JSON.stringify({ target_email: targetEmail }),
    });
    state.modal = null;
    await loadVault(project.id);
    notify(`Access revoked for ${targetEmail}.`);
  } catch (error) {
    notify(error.message, "error");
  }
}

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  const action = button.dataset.action;

  if (action === "backdrop-close" && event.target !== button) return;
  if (action === "close-drawer" && event.target !== button) return;

  if (action === "home") {
    if (state.token) {
      state.section = "overview";
      state.route = "app";
    } else {
      state.route = "home";
    }
    render();
  } else if (action === "open-auth" || action === "switch-auth") {
    state.route = "auth";
    state.authMode = button.dataset.mode;
    renderAuth(button.dataset.mode);
  } else if (action === "navigate" || action === "drawer-navigate") {
    state.section = button.dataset.section;
    state.drawerOpen = false;
    render();
    if (state.section === "vault" && state.selectedProjectId) {
      await loadVault(state.selectedProjectId);
    } else if (state.section === "access") {
      await loadInbox();
    }
  } else if (action === "open-drawer") {
    state.drawerOpen = true;
    render();
  } else if (action === "close-drawer") {
    state.drawerOpen = false;
    render();
  } else if (action === "drawer-help") {
    state.drawerOpen = false;
    state.modal = { kind: "about" };
    render();
  } else if (action === "toggle-theme") {
    setTheme(state.theme === "light" ? "dark" : "light");
  } else if (action === "confirm-sign-out") {
    state.drawerOpen = false;
    state.modal = { kind: "sign-out" };
    render();
  } else if (action === "confirm-sign-out-now") {
    clearSession();
  } else if (action === "new-project") {
    state.drawerOpen = false;
    state.modal = { kind: "project" };
    render();
  } else if (action === "new-secret") {
    if (!selectedProject()) {
      notify("Select a project first.", "error");
      return;
    }
    state.modal = { kind: "secret" };
    render();
  } else if (action === "close-modal" || action === "backdrop-close") {
    state.modal = null;
    render();
  } else if (action === "open-project" || action === "select-project") {
    state.selectedProjectId = button.dataset.projectId;
    state.section = "vault";
    await loadVault(state.selectedProjectId);
  } else if (action === "refresh-vault") {
    if (state.selectedProjectId) await loadVault(state.selectedProjectId);
  } else if (action === "refresh-inbox") {
    await loadInbox();
  } else if (action === "request-access") {
    const project = selectedProject();
    const secretId = button.dataset.secretId;
    if (!project || !secretId) return;
    try {
      const result = await api(
        `/projects/${encodeURIComponent(project.id)}/secrets/${encodeURIComponent(secretId)}/request`,
        { method: "POST" }
      );
      state.secretStatuses[secretId] = {
        ...(state.secretStatuses[secretId] || {}),
        request_id: result.request_id,
        status: result.status,
      };
      await loadVault(project.id);
      notify(result.message || "Access request submitted.");
    } catch (error) {
      notify(error.message, "error");
    }
  } else if (action === "claim-access") {
    const project = selectedProject();
    const secretId = button.dataset.secretId;
    const reqId = state.secretStatuses[secretId]?.request_id;
    if (!project || !secretId) return;
    const reqQuery = reqId ? `?request_id=${encodeURIComponent(reqId)}` : "";
    try {
      const result = await api(
        `/projects/${encodeURIComponent(project.id)}/secrets/${encodeURIComponent(secretId)}/claim${reqQuery}`,
        { method: "POST" }
      );
      state.secretStatuses[secretId] = {
        ...(state.secretStatuses[secretId] || {}),
        request_id: result.request_id,
        status: "claimed",
        access_token: result.access_token,
      };
      render();
      notify("Access token claimed. Click View secret to decrypt.");
    } catch (error) {
      if (error.status === 410) {
        state.secretStatuses[secretId] = { status: "expired" };
        render();
      }
      notify(error.message, "error");
    }
  } else if (action === "view-secret") {
    const secretId = button.dataset.secretId;
    const st = state.secretStatuses[secretId];
    const token = st?.access_token;
    if (!token) {
      notify("No active token in memory. Claim or request access again.", "error");
      return;
    }
    const secretMeta = (state.secrets[state.selectedProjectId] || []).find((s) => s.id === secretId);
    try {
      const result = await api(`/secrets/access/${encodeURIComponent(token)}`, { method: "POST" });
      if (result.views_remaining === 0) {
        state.secretStatuses[secretId] = { status: "none" };
      }
      state.modal = {
        kind: "view-secret",
        secretName: secretMeta?.key_name || "Decrypted secret",
        secretValue: result.secret_value,
        viewsRemaining: result.views_remaining,
      };
      render();
    } catch (error) {
      if (error.status === 403) {
        state.secretStatuses[secretId] = { status: "none" };
        render();
      }
      notify(error.message, "error");
    }
  } else if (action === "copy-secret") {
    const value = document.querySelector("#decrypted-value")?.value;
    if (value) {
      await navigator.clipboard.writeText(value);
      notify("Secret copied to clipboard.");
    }
  } else if (action === "open-audit") {
    const project = selectedProject();
    const secretId = button.dataset.secretId;
    const secretName = button.dataset.secretName;
    if (!project || !secretId) return;
    try {
      const result = await api(
        `/projects/${encodeURIComponent(project.id)}/secrets/${encodeURIComponent(secretId)}/audit?limit=50&skip=0`
      );
      state.modal = { kind: "audit", secretName, logs: result.audit_log || [] };
      render();
    } catch (error) {
      notify(error.message, "error");
    }
  } else if (action === "open-revoke") {
    state.modal = {
      kind: "revoke",
      secretId: button.dataset.secretId,
      secretName: button.dataset.secretName,
    };
    render();
  } else if (action === "inbox-approve" || action === "inbox-reject" || action === "inbox-revoke") {
    const { projectId, secretId, requestId, targetEmail } = button.dataset;
    const endpoint =
      action === "inbox-approve" ? "approve" : action === "inbox-reject" ? "reject" : "revoke";
    const validitySelect = document.querySelector(`select[data-validity-for="${requestId}"]`);
    const approval_validity_seconds = Number(validitySelect?.value || 86400);
    const body =
      endpoint === "approve"
        ? { target_email: targetEmail, request_id: requestId, approval_validity_seconds }
        : { target_email: targetEmail, request_id: requestId };
    try {
      const result = await api(
        `/projects/${encodeURIComponent(projectId)}/secrets/${encodeURIComponent(secretId)}/${endpoint}`,
        { method: "POST", body: JSON.stringify(body) }
      );
      notify(result.message || `Request ${endpoint}d.`);
      await loadInbox();
    } catch (error) {
      notify(error.message, "error");
    }
  }
});

document.addEventListener("submit", async (event) => {
  const form = event.target.closest("form[data-form], #auth-form");
  if (!form) return;
  event.preventDefault();
  if (form.id === "auth-form") {
    await authenticate(form);
  } else if (form.dataset.form === "create-project") {
    await submitProject(form);
  } else if (form.dataset.form === "create-secret") {
    await submitSecret(form);
  } else if (form.dataset.form === "share-project") {
    await submitShare(form);
  } else if (form.dataset.form === "revoke-secret") {
    await submitRevoke(form);
  }
});

document.addEventListener("change", async (event) => {
  if (event.target.id === "project-select") {
    state.selectedProjectId = event.target.value;
    await loadVault(state.selectedProjectId);
  }
});

async function start() {
  if (!state.token) {
    state.route = "home";
    renderHome();
    return;
  }
  try {
    await api("/me");
    await loadProjects();
    state.route = "app";
    render();
  } catch (error) {
    if (state.token) {
      clearSession("auth");
      renderAuth("login", error.message);
    }
  }
}

start();