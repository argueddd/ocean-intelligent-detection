import {
  default as React,
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  BookOpenText,
  ChartBar,
  ChatCircleDots,
  GitDiff,
  GlobeHemisphereWest,
  Graph,
  MapPinArea,
  MicrophoneStage,
  ShareNetwork,
  ShieldCheck,
  SignIn,
  SignOut,
  UserCircle,
} from "@phosphor-icons/react";
import gsap from "gsap";
import AgentChat from "./components/AgentChat";
import { agents } from "./data/agents";

const ParticleStage = lazy(() => import("./components/ParticleStage"));

const agentIcons = [
  ShieldCheck,
  Graph,
  GitDiff,
  MapPinArea,
  MicrophoneStage,
  GlobeHemisphereWest,
  BookOpenText,
  ChartBar,
  ShareNetwork,
];

function BrandMark() {
  return (
    <span className="brand-symbol" aria-hidden="true">
      <svg viewBox="0 0 58 44" role="presentation">
        <path className="brand-orbit" d="M9 22C9 9.8 18.2 4 29 4s20 5.8 20 18-9.2 18-20 18S9 34.2 9 22Z" />
        <path className="brand-links" d="M15 10 29 22 43 10M9 22h40M15 34l14-12 14 12" />
        <circle className="brand-core-halo" cx="29" cy="22" r="6.5" />
        <circle className="brand-core" cx="29" cy="22" r="3.25" />
        <g className="brand-nodes">
          <circle cx="29" cy="4" r="2.15" />
          <circle cx="43" cy="10" r="2.15" />
          <circle cx="49" cy="22" r="2.15" />
          <circle cx="43" cy="34" r="2.15" />
          <circle cx="29" cy="40" r="2.15" />
          <circle cx="15" cy="34" r="2.15" />
          <circle cx="9" cy="22" r="2.15" />
          <circle cx="15" cy="10" r="2.15" />
        </g>
      </svg>
    </span>
  );
}

function getInitialAgent() {
  const params = new URLSearchParams(window.location.search);
  const requested = params.get("agent");
  const found = agents.findIndex((agent) => agent.id === requested);
  return found >= 0 ? found : 0;
}

function currentPortalPath(extraQuery = {}) {
  const url = new URL(window.location.href);
  Object.entries(extraQuery).forEach(([name, value]) => {
    if (value) url.searchParams.set(name, value);
    else url.searchParams.delete(name);
  });
  return `${url.pathname}${url.search}`;
}

function authenticationUrl(returnTo) {
  return `/api/auth/login?return_to=${encodeURIComponent(returnTo)}`;
}

function AuthControl({ auth, loginHref, onLogout }) {
  if (auth.status === "loading") {
    return (
      <span className="auth-loading" role="status">
        <span aria-hidden="true" />
        身份校验中
      </span>
    );
  }

  if (auth.status === "authenticated") {
    const displayName = auth.user.displayName || auth.user.username;
    return (
      <div className="auth-user">
        <UserCircle size={28} weight="duotone" aria-hidden="true" />
        <span className="auth-user-copy">
          <span className="auth-user-state">统一认证</span>
          <strong>{displayName}</strong>
        </span>
        <button
          className="auth-logout"
          type="button"
          onClick={onLogout}
          aria-label={`退出 ${displayName} 的登录`}
          title="退出登录"
        >
          <SignOut size={16} weight="bold" aria-hidden="true" />
        </button>
      </div>
    );
  }

  const hasError = auth.status === "error";
  return (
    <a
      className={`auth-login${hasError ? " auth-login-error" : ""}`}
      href={loginHref}
      title={hasError ? auth.message : "使用统一账号登录"}
    >
      <SignIn size={18} weight="bold" aria-hidden="true" />
      <span>{hasError ? "重新登录" : "统一登录"}</span>
    </a>
  );
}

function HomePage() {
  const [activeIndex, setActiveIndex] = useState(getInitialAgent);
  const [stageStatus, setStageStatus] = useState("loading");
  const [auth, setAuth] = useState({
    status: "loading",
    user: null,
    message: "",
  });
  const rootRef = useRef(null);
  const copyRef = useRef(null);
  const stageFrameRef = useRef(null);
  const carouselRef = useRef(null);
  const cardRefs = useRef([]);
  const active = agents[activeIndex];
  const previous = agents[(activeIndex - 1 + agents.length) % agents.length];
  const next = agents[(activeIndex + 1) % agents.length];
  const loginHref = authenticationUrl(currentPortalPath({ launch: "" }));
  const productLoginHref = authenticationUrl(
    currentPortalPath({ launch: active.launchUrl ? active.id : "" }),
  );
  const launchDisabled =
    auth.status === "loading" ||
    (auth.status === "authenticated" && !active.launchUrl);
  const launchHref =
    auth.status === "authenticated" ? active.launchUrl : productLoginHref;

  const handleStageReady = useCallback(() => setStageStatus("ready"), []);
  const handleStageError = useCallback(() => setStageStatus("error"), []);

  const selectAgent = useCallback((index) => {
    setActiveIndex(index);
    const nextUrl = new URL(window.location.href);
    nextUrl.searchParams.set("agent", agents[index].id);
    window.history.replaceState({}, "", nextUrl);
  }, []);

  useLayoutEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return undefined;

    const context = gsap.context(() => {
      const items = copyRef.current?.querySelectorAll("[data-animate]");
      gsap.fromTo(
        items,
        { y: 18, opacity: 0, filter: "blur(8px)" },
        {
          y: 0,
          opacity: 1,
          filter: "blur(0px)",
          duration: 0.78,
          stagger: 0.065,
          ease: "power3.out",
        },
      );
      gsap.fromTo(
        stageFrameRef.current,
        { scale: 0.975, opacity: 0.72 },
        { scale: 1, opacity: 1, duration: 1.15, ease: "expo.out" },
      );
    }, rootRef);

    return () => context.revert();
  }, [activeIndex]);

  useEffect(() => {
    const nextUrl = new URL(window.location.href);
    const requested = nextUrl.searchParams.get("agent");
    const isKnown = agents.some((agent) => agent.id === requested);
    if (!isKnown) {
      nextUrl.searchParams.set("agent", active.id);
      window.history.replaceState({}, "", nextUrl);
    }
  }, [active.id]);

  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams(window.location.search);
    const callbackError = query.get("auth_error");

    if (callbackError) {
      query.delete("auth_error");
      const cleanedUrl = `${window.location.pathname}${query.size ? `?${query}` : ""}`;
      window.history.replaceState({}, "", cleanedUrl);
    }

    fetch("/api/auth/me", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      signal: controller.signal,
    })
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || "认证服务暂不可用");
        }
        if (payload.authenticated) {
          setAuth({ status: "authenticated", user: payload.user, message: "" });
        } else if (callbackError) {
          setAuth({ status: "error", user: null, message: "统一登录未完成，请重试" });
        } else {
          setAuth({ status: "anonymous", user: null, message: "" });
        }
      })
      .catch((error) => {
        if (error.name !== "AbortError") {
          setAuth({
            status: "error",
            user: null,
            message: error.message || "认证服务暂不可用",
          });
        }
      });

    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (auth.status === "loading") return;

    const url = new URL(window.location.href);
    const launchAgentId = url.searchParams.get("launch");
    if (!launchAgentId) return;

    const launchAgent = agents.find((agent) => agent.id === launchAgentId);
    url.searchParams.delete("launch");
    window.history.replaceState({}, "", `${url.pathname}${url.search}`);

    if (auth.status === "authenticated" && launchAgent?.launchUrl) {
      window.location.assign(launchAgent.launchUrl);
    }
  }, [auth.status]);

  const handleLogout = useCallback(async () => {
    setAuth((current) => ({ ...current, status: "loading" }));
    try {
      const returnTo = `${window.location.pathname}${window.location.search}`;
      const response = await fetch(
        `/api/auth/logout?return_to=${encodeURIComponent(returnTo)}`,
        {
          method: "POST",
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        },
      );
      const payload = await response.json();
      if (!response.ok) throw new Error("退出登录失败");
      window.location.assign(payload.logoutUrl || "/");
    } catch (error) {
      setAuth({
        status: "error",
        user: null,
        message: error.message || "退出登录失败",
      });
    }
  }, []);

  useEffect(() => {
    const viewport = carouselRef.current;
    const card = cardRefs.current[activeIndex];
    if (!viewport || !card) return;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const centerActiveCard = () => {
      const targetLeft =
        card.offsetLeft - (viewport.clientWidth - card.offsetWidth) / 2;
      viewport.scrollTo({
        left: Math.max(0, targetLeft),
        behavior: reduce ? "auto" : "smooth",
      });
    };

    centerActiveCard();
    const observer = new ResizeObserver(centerActiveCard);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, [activeIndex]);

  const handleTabKeyDown = (event, index) => {
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % agents.length;
    else if (event.key === "ArrowLeft") {
      next = (index - 1 + agents.length) % agents.length;
    } else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = agents.length - 1;
    else return;

    event.preventDefault();
    selectAgent(next);
    document.getElementById(`agent-tab-${next}`)?.focus();
  };

  return (
    <main ref={rootRef} className="site-shell">
      <div className="environment-image" aria-hidden="true" />
      <div className="grain" aria-hidden="true" />

      <header className="site-header">
        <a className="brand" href="#top" aria-label="返回智能体中枢首页">
          <BrandMark />
          <span className="brand-title">智能体中枢</span>
        </a>
        <div className="header-tools">
          <div
            className="header-status"
            style={{ "--header-progress": (activeIndex + 1) / agents.length }}
          >
            <span>{String(activeIndex + 1).padStart(2, "0")}</span>
            <i aria-hidden="true" />
            <span>09</span>
          </div>
          <AuthControl auth={auth} loginHref={loginHref} onLogout={handleLogout} />
        </div>
      </header>

      <button
        className="page-arrow page-arrow-left"
        type="button"
        aria-label="上一个智能体"
        onClick={() =>
          selectAgent((activeIndex - 1 + agents.length) % agents.length)
        }
      >
        <ArrowLeft size={22} weight="bold" aria-hidden="true" />
        <span className="page-arrow-label">{previous.short}</span>
      </button>
      <button
        className="page-arrow page-arrow-right"
        type="button"
        aria-label="下一个智能体"
        onClick={() => selectAgent((activeIndex + 1) % agents.length)}
      >
        <ArrowRight size={22} weight="bold" aria-hidden="true" />
        <span className="page-arrow-label">{next.short}</span>
      </button>

      <section className="hero" id="top" aria-labelledby="agent-title">
        <div className="hero-grid">
          <div className="agent-copy" ref={copyRef}>
            <span className="product-index" data-animate aria-hidden="true">
              {String(activeIndex + 1).padStart(2, "0")}
            </span>
            <h1 id="agent-title" data-animate>
              {active.name}
            </h1>
            <p className="agent-statement" data-animate>
              {active.statement}
            </p>
            <p className="agent-description" data-animate>
              {active.description}
            </p>
            <div className="compact-capabilities" data-animate>
              <div className="compact-capabilities-grid">
                {active.capabilities.map(([title, body], index) => (
                  <article className="compact-capability" key={title}>
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <div>
                      <h2>{title}</h2>
                      <p>{body}</p>
                    </div>
                  </article>
                ))}
              </div>
            </div>
            <div className="hero-actions" data-animate>
              <a
                className={`primary-cta${
                  auth.status === "authenticated" && !active.launchUrl
                    ? " is-unavailable"
                    : ""
                }`}
                href={launchDisabled ? undefined : launchHref}
                aria-disabled={launchDisabled}
                onClick={(event) => {
                  if (launchDisabled) event.preventDefault();
                }}
              >
                <span>
                  {auth.status === "loading"
                    ? "身份校验中"
                    : auth.status === "authenticated"
                      ? active.launchUrl
                        ? "前往应用"
                        : "应用接入中"
                      : active.launchUrl
                        ? "登录并进入"
                        : "登录后查看"}
                </span>
                <span className="cta-icon" aria-hidden="true">
                  <ArrowUpRight size={17} weight="bold" />
                </span>
              </a>
              <a
                className="chat-preview-cta"
                href={`/chat?agent=${encodeURIComponent(active.id)}`}
              >
                <ChatCircleDots size={18} weight="duotone" aria-hidden="true" />
                <span>对话原型</span>
              </a>
            </div>
          </div>

          <div className="stage-wrap" ref={stageFrameRef}>
            <div className="stage-aura" aria-hidden="true" />
            <div className="stage-orbits" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
            {stageStatus !== "error" && (
              <Suspense fallback={null}>
                <ParticleStage
                  shape={active.shape}
                  onReady={handleStageReady}
                  onError={handleStageError}
                />
              </Suspense>
            )}
            {stageStatus === "loading" && (
              <div className="stage-loading" role="status">
                <span />
                正在构建空间
              </div>
            )}
            {stageStatus === "error" && (
              <div className="stage-fallback" role="status">
                当前浏览器未启用三维图形功能，已显示静态空间。
              </div>
            )}
          </div>
        </div>

        <div className="agent-carousel">
          <div className="carousel-shell">
            <div
              className="carousel-viewport"
              ref={carouselRef}
              role="tablist"
              aria-label="选择智能体"
            >
              <div className="carousel-track">
                {agents.map((agent, index) => {
                  const offset = index - activeIndex;
                  const distance = Math.min(Math.abs(offset), 4);
                  const AgentIcon = agentIcons[index];
                  return (
                    <button
                    id={`agent-tab-${index}`}
                    ref={(element) => {
                      cardRefs.current[index] = element;
                    }}
                    key={agent.id}
                    className={`agent-card${index === activeIndex ? " active" : ""}`}
                    type="button"
                    role="tab"
                    aria-selected={index === activeIndex}
                    aria-controls="agent-title"
                    tabIndex={index === activeIndex ? 0 : -1}
                    onPointerDown={(event) => {
                      if (event.pointerType === "mouse" && event.button === 0) {
                        selectAgent(index);
                      }
                    }}
                    onClick={() => selectAgent(index)}
                    onKeyDown={(event) => handleTabKeyDown(event, index)}
                    style={{
                      "--card-opacity": 1 - distance * 0.14,
                      "--card-scale": 1 - distance * 0.036,
                      "--card-y": `${distance * 5}px`,
                      "--card-rotate": `${offset * -2.2}deg`,
                    }}
                  >
                    <span className="agent-card-copy">
                      <span className="agent-card-index">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      <span className="agent-card-name">{agent.short}</span>
                    </span>
                    <span className="agent-card-icon" aria-hidden="true">
                      <AgentIcon size={29} weight="duotone" />
                    </span>
                    </button>
                  );
                })}
              </div>
            </div>
            <div className="carousel-progress" aria-hidden="true">
              <span
                style={{
                  "--progress": (activeIndex + 1) / agents.length,
                }}
              />
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}

function App() {
  return window.location.pathname.startsWith("/chat") ? <AgentChat /> : <HomePage />;
}

export default App;
