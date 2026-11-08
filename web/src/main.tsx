import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Fish,
  Plus,
  Folder,
  MessageSquare,
  Settings,
  ChevronDown,
  ArrowUp,
  Square,
  Mic,
  Check,
  RotateCcw,
  X,
  Pencil,
  Radio,
  Plug,
  SlidersHorizontal,
  LoaderCircle,
  Volume2,
  PanelLeftClose,
  PanelLeft,
  Upload,
  RefreshCw,
  CircleAlert,
} from "lucide-react";
import "./style.css";

type Config = {
  asr: Record<string, any>;
  llm: Record<string, any>;
  tts: Record<string, any>;
  endpoint: Record<string, any>;
};
type Conn = {
  id: string;
  name: string;
  preset: string;
  base_url: string;
  kinds: string[];
  has_key?: boolean;
  api_key?: string;
};
type Status = {
  active: string;
  ready: boolean;
  busy: boolean;
  switching: boolean;
  stage: string;
  error: string;
  device: boolean;
  epoch: number;
};
type Msg = { id: number; role: string; content: string; state: string };
type Chat = {
  id: string;
  title: string;
  project: string | null;
  config: Config;
  summary: string;
  covered: number;
  messages: Msg[];
};
type Snapshot = {
  status: Status;
  chats: {
    id: string;
    title: string;
    project: string | null;
    updated: number;
  }[];
  projects: { id: string; name: string }[];
  defaults: Config;
  connections: Conn[];
  presets: { id: string; name: string; kinds: string[]; url: string }[];
  references: { id: string; label: string; seconds: number }[];
};
const stages: Record<string, string> = {
  starting: "服务启动中",
  loading: "正在准备模型",
  restoring: "正在恢复原配置",
  listening: "正在聆听",
  recognizing: "正在识别",
  thinking: "正在组织回答",
  summarizing: "正在整理上下文",
  synthesizing: "正在合成声音",
  playing: "正在回答",
  idle: "准备就绪",
  error: "需要处理",
};
const clone = <T,>(v: T): T => structuredClone(v);
async function api(path: string, method = "GET", body?: unknown) {
  const response = await fetch("/api" + path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string" ? data.detail : "请检查输入参数",
    );
  return data;
}

function App() {
  const [snap, setSnap] = useState<Snapshot>();
  const [chat, setChat] = useState<Chat>();
  const [view, setView] = useState(localStorage.getItem("dafe-view") || "");
  const [text, setText] = useState("");
  const [speak, setSpeak] = useState(false);
  const [settings, setSettings] = useState(false);
  const [tab, setTab] = useState("llm");
  const [draft, setDraft] = useState<Config>();
  const [dirty, setDirty] = useState(false);
  const [defaultsMode, setDefaultsMode] = useState(false);
  const [toast, setToast] = useState("");
  const [working, setWorking] = useState("");
  const [query, setQuery] = useState("");
  const [sidebar, setSidebar] = useState(true);
  const [modelMenu, setModelMenu] = useState(false);
  const [connEditor, setConnEditor] = useState<Conn>();
  const [models, setModels] = useState<Record<string, string[]>>({});
  const [testResult, setTestResult] = useState("");
  const [rename, setRename] = useState<{
    kind: string;
    id?: string;
    name: string;
  }>();
  const [upload, setUpload] = useState(false);
  const [refFile, setRefFile] = useState<File>();
  const [refText, setRefText] = useState("");
  const [refName, setRefName] = useState("");
  const viewRef = useRef(view);
  const listRef = useRef<HTMLDivElement>(null);
  const nearBottom = useRef(true);
  const bottom = useRef<HTMLDivElement>(null);
  viewRef.current = view;
  async function refresh() {
    const next = await api("/state");
    setSnap(next);
    if (!viewRef.current)
      setView(next.status.active || next.chats[0]?.id || "");
  }
  async function load(id: string) {
    if (!id) return;
    const next = await api("/chats/" + id);
    if (viewRef.current !== id) return;
    setChat((previous) => {
      if (previous?.id === id) {
        next.messages = next.messages.map((m: Msg) => {
          const prior = previous.messages.find((p) => p.id === m.id);
          return m.state === "streaming" &&
            prior &&
            prior.content.length > m.content.length
            ? { ...m, content: prior.content }
            : m;
        });
      }
      return next;
    });
  }
  async function action(label: string, fn: () => Promise<void>) {
    if (working) return;
    setWorking(label);
    try {
      await fn();
    } catch (e) {
      setToast((e as Error).message);
    } finally {
      setWorking("");
    }
  }
  useEffect(() => {
    refresh().catch((e) => setToast(e.message));
    let socket: WebSocket;
    let timer: ReturnType<typeof setTimeout>;
    let dead = false;
    function connect() {
      socket = new WebSocket(`ws://${location.host}/api/events`);
      socket.onmessage = (ev) => {
        const e = JSON.parse(ev.data);
        setSnap((s) => (s ? { ...s, status: e.status } : s));
        if (e.type === "delta" && e.chat === viewRef.current) {
          setChat((c) => {
            if (!c || c.id !== e.chat) return c;
            const found = c.messages.some((m) => m.id === e.message);
            const message: Msg = {
              id: e.message,
              role: "assistant",
              content: e.content,
              state: "streaming",
            };
            return {
              ...c,
              messages: found
                ? c.messages.map((m) =>
                    m.id === e.message && e.content.length >= m.content.length
                      ? { ...m, content: e.content }
                      : m,
                  )
                : [...c.messages, message],
            };
          });
        }
        if (e.type === "refresh" || e.type === "resync") {
          refresh().catch(() => {});
          load(viewRef.current).catch(() => {});
        }
      };
      socket.onclose = () => {
        if (!dead) timer = setTimeout(connect, 1500);
      };
    }
    connect();
    return () => {
      dead = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, []);
  useEffect(() => {
    localStorage.setItem("dafe-view", view);
    nearBottom.current = true;
    load(view).catch((e) => setToast(e.message));
  }, [view]);
  useEffect(() => {
    if (nearBottom.current)
      bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat?.messages.map((m) => m.content).join("")]);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 6500);
    return () => clearTimeout(t);
  }, [toast]);
  async function newChat(project: string | null = null) {
    await action("新建对话", async () => {
      const c = await api("/chats", "POST", { project });
      setView(c.id);
      setSettings(false);
      await refresh();
    });
  }
  function openSettings(defaults = false) {
    if (!snap || !chat) return;
    setDefaultsMode(defaults);
    setDraft(clone(defaults ? snap.defaults : chat.config));
    setDirty(false);
    setTestResult("");
    setSettings(true);
  }
  function edit(section: string, key: string, value: any) {
    setDraft((d) =>
      d ? { ...d, [section]: { ...(d as any)[section], [key]: value } } : d,
    );
    setDirty(true);
  }
  async function saveConfig() {
    if (!draft || !chat) return;
    await action("保存配置", async () => {
      await api(
        defaultsMode ? "/defaults" : `/chats/${chat.id}/config`,
        "PUT",
        draft,
      );
      setDirty(false);
      setToast(
        defaultsMode
          ? "默认配置已保存，新对话将继承它"
          : "配置已保存" +
              (chat.id === snap?.status.active
                ? "并应用"
                : "，启用此对话时生效"),
      );
      await refresh();
      await load(chat.id);
    });
  }
  async function fetchModels(id: string) {
    await action("获取模型", async () => {
      const result = await api(`/connections/${id}/models`);
      setModels((m) => ({ ...m, [id]: result.models }));
      setToast("已更新模型列表，也可手填模型 ID");
    });
  }
  async function test(kind: string) {
    if (!draft) return;
    const s = (draft as any)[kind];
    if (s.connection === "local") {
      setTestResult(
        "本地模型在“保存并应用”或“确定启用”时实际加载验证；不会播放测试音。",
      );
      return;
    }
    await action("测试连接", async () => {
      setTestResult("正在发起接口测试…");
      try {
        const r = await api(`/connections/${s.connection}/test`, "POST", {
          kind,
          model: s.model,
          voice: draft.tts.voice,
        });
        setTestResult(r.detail);
      } catch (e) {
        setTestResult((e as Error).message);
      }
    });
  }
  const status = snap?.status;
  const activeTitle =
    snap?.chats.find((c) => c.id === status?.active)?.title || "尚未启用";
  const waiting = !!working || !!status?.switching;
  const active = chat?.id === status?.active;
  const fields = (kind: string) => {
    if (!draft || !snap) return null;
    const s = (draft as any)[kind];
    return (
      <>
        <label>
          运行方式 / 连接
          <select
            value={s.connection}
            onChange={(e) => {
              edit(kind, "connection", e.target.value);
              if (e.target.value === "local")
                edit(
                  kind,
                  "model",
                  kind === "asr"
                    ? snap.defaults.asr.model
                    : snap.defaults.tts.model,
                );
              else edit(kind, "model", "");
            }}
          >
            {kind !== "llm" && (
              <option value="local">
                本机内置 ·{" "}
                {kind === "asr" ? "Paraformer 流式识别" : "VoxCPM2 固定音色"}
              </option>
            )}
            {snap.connections
              .filter((c) => c.kinds.includes(kind))
              .map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
          </select>
        </label>
        <label>
          {s.connection === "local" ? "本地模型路径" : "模型 ID"}
          <div className="inline">
            <input
              value={s.model}
              list={"models-" + kind}
              onChange={(e) => edit(kind, "model", e.target.value)}
              placeholder="选择或输入模型 ID"
            />
            {s.connection !== "local" && (
              <button
                className="icon"
                title="获取模型列表"
                disabled={waiting}
                onClick={() => fetchModels(s.connection)}
              >
                <RefreshCw size={16} />
              </button>
            )}
          </div>
          <datalist id={"models-" + kind}>
            {(models[s.connection] || []).map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </label>
        {s.connection !== "local" && (
          <div className="hint">
            {snap.connections.find((c) => c.id === s.connection)?.base_url ||
              "请选择已配置的连接"}{" "}
            · 密钥
            {snap.connections.find((c) => c.id === s.connection)?.has_key
              ? "已保存"
              : "未设置 / 本地免密"}
          </div>
        )}
      </>
    );
  };
  const number = (
    section: string,
    key: string,
    title: string,
    min: number,
    max: number,
    step = 1,
  ) => (
    <label>
      {title}
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={(draft as any)?.[section][key] ?? ""}
        onChange={(e) =>
          edit(
            section,
            key,
            e.target.value === "" ? null : Number(e.target.value),
          )
        }
      />
    </label>
  );
  const listed = (p: string | null) =>
    snap?.chats.filter(
      (c) =>
        (p === null || c.project === p) &&
        c.title.toLowerCase().includes(query.toLowerCase()),
    );
  const chatRow = (c: { id: string; title: string }) => (
    <div key={c.id} className={"chat-row " + (view === c.id ? "selected" : "")}>
      <button
        onClick={() => {
          setView(c.id);
          setSettings(false);
        }}
      >
        <MessageSquare size={15} />
        <span>{c.title}</span>
        {status?.active === c.id && (
          <span className="live-dot" title="ESP32 当前使用" />
        )}
      </button>
      <button
        className="rename-row"
        title="重命名对话"
        onClick={() => setRename({ kind: "chat", id: c.id, name: c.title })}
      >
        <Pencil size={12} />
      </button>
    </div>
  );
  if (!snap)
    return (
      <div className="boot">
        <Fish size={42} />
        <h2>大肥鱼</h2>
        <p>正在打开工作台…</p>
        {toast && <p>{toast}</p>}
      </div>
    );
  return (
    <div className={"app " + (!sidebar ? "collapsed" : "")}>
      {sidebar && (
        <aside>
          <div className="brand">
            <span className="brand-mark">
              <Fish size={23} />
            </span>
            <div>
              大肥鱼<span>VOICE WORKSPACE</span>
            </div>
            <button
              className="icon"
              title="收起侧栏"
              onClick={() => setSidebar(false)}
            >
              <PanelLeftClose size={17} />
            </button>
          </div>
          <button
            className="new-chat"
            disabled={waiting}
            onClick={() => newChat()}
          >
            <Plus size={17} />
            新建对话<span>＋</span>
          </button>
          <input
            className="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索对话…"
            aria-label="搜索对话"
          />
          <div className="sidebar-scroll">
            <div className="section-label">
              最近对话<span>{snap.chats.length}</span>
            </div>
            {listed(null)?.slice(0, 12).map(chatRow)}
            <div className="section-label project-heading">
              项目
              <button
                className="icon"
                title="新建项目"
                onClick={() => setRename({ kind: "project", name: "" })}
              >
                <Plus size={14} />
              </button>
            </div>
            {snap.projects.length === 0 && (
              <p className="empty-side">用项目整理不同主题，记忆仍独立。</p>
            )}
            {snap.projects.map((p) => (
              <section className="project" key={p.id}>
                <div className="project-label">
                  <Folder size={15} />
                  <span>{p.name}</span>
                  <button
                    className="icon"
                    title="重命名项目"
                    onClick={() =>
                      setRename({ kind: "project", id: p.id, name: p.name })
                    }
                  >
                    <Pencil size={12} />
                  </button>
                  <button
                    className="icon"
                    title="在项目中新建对话"
                    onClick={() => newChat(p.id)}
                  >
                    <Plus size={13} />
                  </button>
                </div>
                {listed(p.id)?.map(chatRow)}
              </section>
            ))}
          </div>
          <div className="sidebar-bottom">
            <button
              onClick={() => openSettings()}
              className={settings ? "chosen" : ""}
            >
              <Settings size={17} />
              设置与模型
            </button>
            <div className="device-card">
              <span
                className={"device-light " + (status?.device ? "online" : "")}
              />
              <div>
                ESP32
                <span>{status?.device ? "设备已连接" : "等待设备连接"}</span>
              </div>
              <span className="device-tag">Wi-Fi</span>
            </div>
            <div className="local-note">
              本地工作台 <span>·</span> 你的对话只属于你
            </div>
          </div>
        </aside>
      )}
      <main>
        <header>
          {!sidebar && (
            <button
              className="icon"
              title="展开侧栏"
              onClick={() => setSidebar(true)}
            >
              <PanelLeft size={19} />
            </button>
          )}
          <div className="breadcrumbs">
            工作台<span>/</span>
            <strong>{settings ? "设置" : chat?.title || "选择对话"}</strong>
          </div>
          <div className="header-right">
            <span className={"status-badge " + (status?.ready ? "good" : "")}>
              <span />
              {stages[status?.stage || ""] || status?.stage}
            </span>
            <span className="local-badge">LOCAL</span>
          </div>
        </header>
        <div className="active-strip">
          <Radio size={14} />
          <span>ESP32 当前对话</span>
          <strong>{activeTitle}</strong>
          <span className="strip-separator" />
          <span>
            {active ? "正在浏览当前对话" : "浏览其他对话不会改变设备上下文"}
          </span>
        </div>
        {status?.error && (
          <div className="error-banner">
            <CircleAlert size={16} />
            {status.error}
            <button
              disabled={waiting}
              onClick={() =>
                action("重试", async () => {
                  await api(`/chats/${status.active}/activate`, "POST");
                })
              }
            >
              重试当前配置
            </button>
          </div>
        )}
        {settings && draft && chat ? (
          <div className="settings-page">
            <div className="page-title">
              <div>
                <span className="eyebrow">PREFERENCES</span>
                <h1>让大肥鱼更懂你</h1>
                <p>配置这次对话的三个模型，保留你喜欢的声音。</p>
              </div>
              <button
                className="soft"
                disabled={waiting}
                onClick={() => {
                  setDraft(clone(snap.defaults));
                  setDirty(true);
                  setToast("已载入默认参数；保存后生效，密钥保持不变");
                }}
              >
                <RotateCcw size={15} />
                恢复默认
              </button>
            </div>
            <div className="settings-scope">
              <button
                className={!defaultsMode ? "on" : ""}
                onClick={() => openSettings(false)}
              >
                当前对话 · {chat.title}
              </button>
              <button
                className={defaultsMode ? "on" : ""}
                onClick={() => openSettings(true)}
              >
                新对话默认配置
              </button>
              <span>{dirty ? "有未保存的修改" : "已保存"}</span>
            </div>
            <nav className="tabs">
              {[
                ["llm", "LLM · 对话"],
                ["asr", "ASR · 听懂"],
                ["tts", "TTS · 发声"],
                ["endpoint", "监听"],
                ["connections", "连接与密钥"],
              ].map(([id, title]) => (
                <button
                  key={id}
                  className={tab === id ? "on" : ""}
                  onClick={() => {
                    setTab(id);
                    setTestResult("");
                  }}
                >
                  {title}
                </button>
              ))}
            </nav>
            <div className="settings-card">
              {tab === "llm" && (
                <>
                  <div className="card-title">
                    <MessageSquare size={19} />
                    <div>
                      <h2>语言模型</h2>
                      <p>每个对话有自己的模型与记忆。</p>
                    </div>
                  </div>
                  {fields("llm")}
                  <label>
                    系统提示词
                    <textarea
                      rows={4}
                      value={draft.llm.system}
                      onChange={(e) => edit("llm", "system", e.target.value)}
                    />
                  </label>
                  <div className="field-grid">
                    {number(
                      "llm",
                      "temperature",
                      "温度（留空为厂商默认）",
                      0,
                      2,
                      0.1,
                    )}
                    {number("llm", "max_tokens", "最大输出 tokens", 16, 8192)}
                    {number(
                      "llm",
                      "context_budget",
                      "模型上下文预算 tokens",
                      2048,
                      262144,
                    )}
                    {number(
                      "llm",
                      "recent_turns",
                      "摘要后保留的近期轮数",
                      1,
                      30,
                    )}
                    {number(
                      "llm",
                      "summary_after",
                      "触发摘要的未归档轮数",
                      2,
                      100,
                    )}
                  </div>
                  {snap.connections.find((c) => c.id === draft.llm.connection)
                    ?.preset === "deepseek" && (
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={draft.llm.thinking}
                        onChange={(e) =>
                          edit("llm", "thinking", e.target.checked)
                        }
                      />
                      开启 DeepSeek 思考（默认关闭）
                    </label>
                  )}
                  <p className="hint">
                    完整记录始终保存。旧内容只归入本对话的摘要，不与其他对话共享。
                  </p>
                </>
              )}
              {tab === "asr" && (
                <>
                  <div className="card-title">
                    <Mic size={20} />
                    <div>
                      <h2>语音识别</h2>
                      <p>将你说的话转成这次对话的文字。</p>
                    </div>
                  </div>
                  {fields("asr")}
                  {draft.asr.connection === "local" ? (
                    <>
                      <div className="notice">
                        本机 Paraformer · 说话时增量识别 · 默认每 600ms 解码
                      </div>
                      <div className="field-grid">
                        {number("asr", "threads", "CPU 线程数", 1, 16)}
                        {number(
                          "asr",
                          "chunk_size",
                          "解码块（每单位 60ms）",
                          5,
                          20,
                        )}
                        {number(
                          "asr",
                          "encoder_lookback",
                          "Encoder 回看块数",
                          0,
                          16,
                        )}
                        {number(
                          "asr",
                          "decoder_lookback",
                          "Decoder 回看块数",
                          0,
                          16,
                        )}
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="notice">
                        兼容转写 API · 说完后整句转写；音频会发送给该服务。
                      </div>
                      <label>
                        语言代码
                        <input
                          value={draft.asr.language}
                          onChange={(e) =>
                            edit("asr", "language", e.target.value)
                          }
                        />
                      </label>
                    </>
                  )}
                </>
              )}
              {tab === "tts" && (
                <>
                  <div className="card-title">
                    <Volume2 size={20} />
                    <div>
                      <h2>语音合成</h2>
                      <p>保留一个声音，也可以表达不同的语气。</p>
                    </div>
                  </div>
                  {fields("tts")}
                  {draft.tts.connection === "local" ? (
                    <>
                      <label>
                        唯一参考音
                        <div className="inline">
                          <select
                            value={draft.tts.reference}
                            onChange={(e) =>
                              edit("tts", "reference", e.target.value)
                            }
                          >
                            {snap.references.map((r) => (
                              <option key={r.id} value={r.id}>
                                {r.label} · {r.seconds.toFixed(1)} 秒
                              </option>
                            ))}
                          </select>
                          <button
                            className="soft"
                            onClick={() => setUpload(true)}
                          >
                            <Upload size={15} />
                            导入
                          </button>
                        </div>
                      </label>
                      <audio
                        controls
                        preload="none"
                        src={`/api/references/${draft.tts.reference}/audio`}
                      />
                      <div className="field-grid">
                        {number("tts", "steps", "推理步数", 1, 20)}
                        {number("tts", "cfg", "CFG", 0.5, 4, 0.1)}
                        {number("tts", "seed", "随机种子", 0, 2147483647)}
                        <label>
                          运行设备
                          <select
                            value={draft.tts.device}
                            onChange={(e) =>
                              edit("tts", "device", e.target.value)
                            }
                          >
                            <option value="cuda">CUDA · NVIDIA GPU</option>
                            <option value="cpu">CPU（速度较慢）</option>
                          </select>
                        </label>
                      </div>
                      {draft.tts.steps < 5 && (
                        <div className="warning">
                          本机实测：1、2、3 步出现明显噪声，不建议用于对话。
                        </div>
                      )}
                      <p className="hint">
                        默认 jm-tech / 5 步 / CFG 2.0 / seed 0。48kHz
                        输出，未加入额外音量稳定处理。流式模式不支持坏例自动重试。
                      </p>
                    </>
                  ) : (
                    <div className="field-grid">
                      <label>
                        Voice ID
                        <input
                          value={draft.tts.voice}
                          onChange={(e) => edit("tts", "voice", e.target.value)}
                        />
                      </label>
                      {number("tts", "speed", "语速", 0.25, 4, 0.05)}
                    </div>
                  )}
                </>
              )}
              {tab === "endpoint" && (
                <>
                  <div className="card-title">
                    <SlidersHorizontal size={20} />
                    <div>
                      <h2>监听与句尾</h2>
                      <p>保持已经验证的轮流对话方式。</p>
                    </div>
                  </div>
                  <div className="field-grid">
                    {number(
                      "endpoint",
                      "threshold",
                      "声音阈值 RMS",
                      0.0001,
                      0.2,
                      0.0001,
                    )}
                    {number(
                      "endpoint",
                      "silence_ms",
                      "句尾静音 ms",
                      200,
                      3000,
                      50,
                    )}
                    {number(
                      "endpoint",
                      "pre_roll_ms",
                      "说话前预录 ms",
                      0,
                      1000,
                      50,
                    )}
                    {number("endpoint", "max_seconds", "最长讲话秒数", 2, 60)}
                  </div>
                  <p className="hint">
                    回答期间暂停监听，播完再恢复。开机和待机不播放提示音。
                  </p>
                </>
              )}
              {tab === "connections" && (
                <>
                  <div className="card-title">
                    <Plug size={20} />
                    <div>
                      <h2>模型连接</h2>
                      <p>密钥仅保存在本机；界面不会读取已保存的密钥。</p>
                    </div>
                    <button
                      className="soft"
                      onClick={() => {
                        setConnEditor({
                          id: crypto.randomUUID(),
                          name: "新连接",
                          preset: "compatible",
                          base_url: "",
                          kinds: ["llm"],
                          api_key: "",
                        });
                        setTestResult("");
                      }}
                    >
                      <Plus size={15} />
                      添加连接
                    </button>
                  </div>
                  {snap.connections.map((c) => (
                    <button
                      className="connection-row"
                      key={c.id}
                      onClick={() => {
                        setConnEditor({ ...c, api_key: "" });
                        setTestResult("");
                      }}
                    >
                      <span className="connection-icon">
                        {c.name.slice(0, 1)}
                      </span>
                      <div>
                        <strong>{c.name}</strong>
                        <small>{c.base_url}</small>
                      </div>
                      <span>{c.kinds.join(" / ").toUpperCase()}</span>
                      <span className="key-state">
                        {c.has_key ? "密钥已配置" : "本地 / 未设置"}
                      </span>
                      <Pencil size={14} />
                    </button>
                  ))}
                  <p className="hint">
                    首版支持 OpenAI 兼容协议。Ollama / LM Studio
                    需由你启动本地服务。DeepSeek 仅用于 LLM。
                  </p>
                </>
              )}
              {testResult && (
                <div className="notice" role="status">
                  {testResult}
                </div>
              )}
            </div>
            <div className="settings-footer">
              <button
                className="soft"
                onClick={() => {
                  setSettings(false);
                  setDirty(false);
                }}
              >
                返回对话
              </button>
              {["llm", "asr", "tts"].includes(tab) && (
                <button
                  className="soft"
                  disabled={waiting}
                  onClick={() => test(tab)}
                >
                  测试连接
                  {(draft as any)[tab].connection !== "local"
                    ? "（可能计费）"
                    : ""}
                </button>
              )}
              <span />
              {!defaultsMode && (
                <button
                  className="soft"
                  disabled={waiting}
                  onClick={() =>
                    action("保存默认", async () => {
                      await api("/defaults", "PUT", draft);
                      await refresh();
                      setToast("已保存为新对话默认配置，当前对话未改动");
                    })
                  }
                >
                  保存为默认
                </button>
              )}
              <button
                className="primary"
                disabled={waiting || !!status?.busy}
                onClick={saveConfig}
              >
                {waiting ? (
                  <LoaderCircle className="spin" size={16} />
                ) : (
                  <Check size={16} />
                )}{" "}
                {defaultsMode
                  ? "保存默认配置"
                  : active
                    ? "保存并应用"
                    : "保存对话配置"}
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="chat-toolbar">
              <div className="toolbar-left">
                <select
                  className="project-select"
                  aria-label="所属项目"
                  value={chat?.project || ""}
                  onChange={(e) =>
                    chat &&
                    action("移动对话", async () => {
                      await api("/chats/" + chat.id, "PATCH", {
                        project: e.target.value || null,
                      });
                      await refresh();
                      await load(chat.id);
                    })
                  }
                >
                  <option value="">无项目</option>
                  {snap.projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
                <div className="model-picker">
                  <SlidersHorizontal size={15} />
                  <select
                    aria-label="对话LLM连接"
                    value={chat?.config.llm.connection || ""}
                    disabled={waiting || status?.busy}
                    onChange={(e) => {
                      if (!chat) return;
                      const c = clone(chat.config);
                      c.llm.connection = e.target.value;
                      c.llm.model = "";
                      setDraft(c);
                      setDefaultsMode(false);
                      setSettings(true);
                      setTab("llm");
                      setDirty(true);
                    }}
                  >
                    {snap.connections
                      .filter((c) => c.kinds.includes("llm"))
                      .map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                  </select>
                  <span className="picker-divider" />
                  <input
                    aria-label="对话模型"
                    list="chat-models"
                    value={chat?.config.llm.model || ""}
                    disabled={waiting || status?.busy}
                    onChange={(e) =>
                      setChat((c) =>
                        c
                          ? {
                              ...c,
                              config: {
                                ...c.config,
                                llm: { ...c.config.llm, model: e.target.value },
                              },
                            }
                          : c,
                      )
                    }
                    onBlur={() => {
                      if (chat)
                        action("更换模型", async () => {
                          const saved = await api("/chats/" + chat.id);
                          if (
                            saved.config.llm.model !== chat.config.llm.model
                          ) {
                            await api(
                              `/chats/${chat.id}/config`,
                              "PUT",
                              chat.config,
                            );
                            await load(chat.id);
                          }
                        });
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") e.currentTarget.blur();
                    }}
                  />
                  <datalist id="chat-models">
                    {(models[chat?.config.llm.connection || ""] || []).map(
                      (m) => (
                        <option key={m} value={m} />
                      ),
                    )}
                  </datalist>
                  <button
                    className="icon"
                    title="获取可用模型"
                    disabled={waiting}
                    onClick={() => {
                      setModelMenu((v) => !v);
                      if (chat && !models[chat.config.llm.connection])
                        fetchModels(chat.config.llm.connection);
                    }}
                  >
                    <ChevronDown size={14} />
                  </button>
                  {modelMenu && (
                    <div className="model-menu">
                      {(models[chat?.config.llm.connection || ""] || []).map(
                        (m) => (
                          <button
                            key={m}
                            onClick={() =>
                              chat &&
                              action("更换模型", async () => {
                                const config = clone(chat.config);
                                config.llm.model = m;
                                await api(
                                  `/chats/${chat.id}/config`,
                                  "PUT",
                                  config,
                                );
                                await load(chat.id);
                                setModelMenu(false);
                              })
                            }
                          >
                            {m}
                            {m === chat?.config.llm.model && (
                              <Check size={14} />
                            )}
                          </button>
                        ),
                      )}
                      <p>也可在上方直接输入模型 ID，按 Enter 应用。</p>
                    </div>
                  )}
                </div>
              </div>
              <button
                className={active && status?.ready ? "activated" : "primary"}
                disabled={waiting || !chat}
                onClick={() =>
                  chat &&
                  action("启用对话", async () => {
                    await api(`/chats/${chat.id}/activate`, "POST");
                    await refresh();
                    await load(chat.id);
                    setToast("ESP32 已切换到此对话");
                  })
                }
              >
                {waiting ? (
                  <LoaderCircle className="spin" size={15} />
                ) : (
                  <Check size={15} />
                )}{" "}
                {status?.switching
                  ? "正在准备…"
                  : active && status?.ready
                    ? "当前已启用"
                    : "确定启用"}
              </button>
            </div>
            <div
              className="messages"
              ref={listRef}
              onScroll={() => {
                const el = listRef.current;
                if (el)
                  nearBottom.current =
                    el.scrollHeight - el.scrollTop - el.clientHeight < 140;
              }}
            >
              {!chat?.messages.length ? (
                <div className="welcome">
                  <div className="welcome-mark">
                    <Fish size={43} strokeWidth={1.4} />
                  </div>
                  <span className="eyebrow">YOUR LITTLE VOICE COMPANION</span>
                  <h1>今天，想聊些什么？</h1>
                  <p>
                    在这里打字，或对大肥鱼说句话。
                    <br />
                    每个对话，都有属于自己的记忆。
                  </p>
                  <div className="suggestions">
                    {[
                      "你好，大肥鱼，请介绍一下自己。",
                      "我叫小杨，请记住。",
                      "陪我聊聊今天的计划。",
                    ].map((t) => (
                      <button key={t} onClick={() => setText(t)}>
                        {t}
                        <ArrowUp size={13} />
                      </button>
                    ))}
                  </div>
                  <div className="welcome-note">
                    <span className="live-dot" />
                    {active
                      ? status?.device
                        ? "这个对话已连接到 ESP32"
                        : "此对话已启用，等待 ESP32 连接"
                      : "浏览完成后，点击右上角“确定启用”连接 ESP32"}
                  </div>
                </div>
              ) : (
                <div className="message-column">
                  {chat.messages.map((m) => (
                    <article key={m.id} className={"message " + m.role}>
                      <div className="avatar">
                        {m.role === "user" ? "你" : <Fish size={18} />}
                      </div>
                      <div className="message-content">
                        <div className="message-name">
                          {m.role === "user" ? "你" : "大肥鱼"}
                          <span>
                            {m.state === "streaming"
                              ? "正在回复"
                              : m.state === "interrupted"
                                ? "已中断"
                                : m.state === "error"
                                  ? "未完成"
                                  : ""}
                          </span>
                        </div>
                        <div className="message-body">
                          {m.content || (
                            <span className="thinking-dots">正在想…</span>
                          )}
                          {m.state === "streaming" && (
                            <span className="cursor" />
                          )}
                        </div>
                        {m.role === "assistant" &&
                          ["error", "interrupted"].includes(m.state) && (
                            <button
                              className="retry-message"
                              disabled={waiting || status?.busy}
                              onClick={() =>
                                action("重试回答", async () => {
                                  const source = chat.messages
                                    .filter(
                                      (v) => v.role === "user" && v.id < m.id,
                                    )
                                    .at(-1);
                                  if (source)
                                    await api(
                                      `/chats/${chat.id}/messages`,
                                      "POST",
                                      { text: source.content, speak: false },
                                    );
                                })
                              }
                            >
                              <RotateCcw size={12} />
                              重试文字回答
                            </button>
                          )}
                      </div>
                    </article>
                  ))}
                  <div ref={bottom} />
                </div>
              )}
            </div>
            {chat?.summary && (
              <details className="memory">
                <summary>本对话记忆摘要 · 已归档至消息 #{chat.covered}</summary>
                <p>{chat.summary}</p>
              </details>
            )}
            <div className="composer-wrap">
              <div className="composer">
                <textarea
                  aria-label="消息"
                  placeholder="给大肥鱼发消息…"
                  value={text}
                  rows={2}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => {
                    if (
                      e.key === "Enter" &&
                      !e.shiftKey &&
                      !e.nativeEvent.isComposing
                    ) {
                      e.preventDefault();
                      if (text.trim() && !waiting && !status?.busy)
                        document.getElementById("send-message")?.click();
                    }
                  }}
                />
                <div className="composer-bottom">
                  <label className={"speak-toggle " + (speak ? "enabled" : "")}>
                    <input
                      type="checkbox"
                      checked={speak}
                      onChange={(e) => setSpeak(e.target.checked)}
                    />
                    <Volume2 size={15} />
                    本次朗读
                  </label>
                  <button
                    className="icon"
                    title="对话设置"
                    onClick={() => openSettings()}
                  >
                    <SlidersHorizontal size={16} />
                  </button>
                  <span />
                  <span className="enter-hint">
                    Enter 发送 · Shift Enter 换行
                  </span>
                  {status?.busy ? (
                    <button
                      className="send stop"
                      title="停止回答"
                      onClick={() =>
                        action("停止", async () => {
                          await api("/stop", "POST");
                        })
                      }
                    >
                      <Square size={15} fill="currentColor" />
                    </button>
                  ) : (
                    <button
                      id="send-message"
                      className="send"
                      title="发送消息"
                      disabled={!text.trim() || waiting}
                      onClick={() =>
                        chat &&
                        action("发送", async () => {
                          await api(`/chats/${chat.id}/messages`, "POST", {
                            text,
                            speak,
                          });
                          setText("");
                          nearBottom.current = true;
                          await load(chat.id);
                        })
                      }
                    >
                      <ArrowUp size={20} />
                    </button>
                  )}
                </div>
              </div>
              <div className="composer-caption">
                <span>
                  {status?.device ? (
                    <>
                      <Mic size={12} /> {stages[status.stage] || status.stage}
                    </>
                  ) : (
                    <>○ ESP32 未连接，仍可文字聊天</>
                  )}
                </span>
                <button onClick={() => openSettings()}>管理模型与配置</button>
              </div>
            </div>
          </>
        )}
      </main>
      {toast && (
        <div className="toast" role="status">
          {toast}
          <button className="icon" onClick={() => setToast("")}>
            <X size={14} />
          </button>
        </div>
      )}
      {rename && (
        <div className="modal-backdrop">
          <form
            className="modal small"
            onSubmit={(e) => {
              e.preventDefault();
              action("保存名称", async () => {
                if (rename.kind === "project")
                  await api(
                    "/projects" + (rename.id ? "/" + rename.id : ""),
                    rename.id ? "PATCH" : "POST",
                    { name: rename.name },
                  );
                else
                  await api("/chats/" + rename.id, "PATCH", {
                    title: rename.name,
                  });
                setRename(undefined);
                await refresh();
                await load(view);
              });
            }}
          >
            <h2>{rename.id ? "重命名" : "新建项目"}</h2>
            <label>
              名称
              <input
                autoFocus
                required
                maxLength={100}
                value={rename.name}
                onChange={(e) => setRename({ ...rename, name: e.target.value })}
              />
            </label>
            <div className="modal-actions">
              <button
                type="button"
                className="soft"
                onClick={() => setRename(undefined)}
              >
                取消
              </button>
              <button className="primary" disabled={waiting}>
                保存
              </button>
            </div>
          </form>
        </div>
      )}
      {connEditor && (
        <div className="modal-backdrop">
          <form
            className="modal"
            onSubmit={(e) => {
              e.preventDefault();
              action("保存连接", async () => {
                const { id, has_key, ...config } = connEditor;
                await api("/connections/" + id, "PUT", {
                  ...config,
                  api_key: config.api_key || null,
                });
                setConnEditor(undefined);
                await refresh();
                setToast("连接已保存；在模型页选择并测试后应用");
              });
            }}
          >
            <div className="modal-title">
              <h2>模型连接</h2>
              <button
                type="button"
                className="icon"
                onClick={() => setConnEditor(undefined)}
              >
                <X size={18} />
              </button>
            </div>
            <label>
              厂商预设
              <select
                value={connEditor.preset}
                onChange={(e) => {
                  const preset = snap.presets.find(
                    (p) => p.id === e.target.value,
                  )!;
                  setConnEditor({
                    ...connEditor,
                    preset: preset.id,
                    name: preset.name,
                    base_url: preset.url,
                    kinds: [preset.kinds[0]],
                  });
                }}
              >
                {snap.presets.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              连接名称
              <input
                required
                value={connEditor.name}
                onChange={(e) =>
                  setConnEditor({ ...connEditor, name: e.target.value })
                }
              />
            </label>
            <label>
              API Base URL
              <input
                required
                type="url"
                placeholder="https://…/v1"
                value={connEditor.base_url}
                onChange={(e) =>
                  setConnEditor({ ...connEditor, base_url: e.target.value })
                }
              />
            </label>
            <label>
              API Key
              <input
                type="password"
                autoComplete="new-password"
                placeholder={
                  connEditor.has_key
                    ? "已保存；留空保持不变"
                    : "本地免密服务可留空"
                }
                value={connEditor.api_key}
                onChange={(e) =>
                  setConnEditor({ ...connEditor, api_key: e.target.value })
                }
              />
            </label>
            <label>支持的接口</label>
            <div className="capabilities">
              {snap.presets
                .find((p) => p.id === connEditor.preset)
                ?.kinds.map((k) => (
                  <label className="checkbox" key={k}>
                    <input
                      type="checkbox"
                      checked={connEditor.kinds.includes(k)}
                      onChange={(e) =>
                        setConnEditor({
                          ...connEditor,
                          kinds: e.target.checked
                            ? [...connEditor.kinds, k]
                            : connEditor.kinds.filter((v) => v !== k),
                        })
                      }
                    />
                    {k.toUpperCase()}
                  </label>
                ))}
            </div>
            <p className="hint">
              密钥仅存本机，留空不覆盖旧密钥。保存连接不会自动切换当前对话。
            </p>
            <div className="modal-actions">
              <button
                type="button"
                className="soft"
                onClick={() => setConnEditor(undefined)}
              >
                取消
              </button>
              <button
                className="primary"
                disabled={waiting || !connEditor.kinds.length}
              >
                保存连接
              </button>
            </div>
          </form>
        </div>
      )}
      {upload && (
        <div className="modal-backdrop">
          <form
            className="modal"
            onSubmit={(e) => {
              e.preventDefault();
              action("导入参考音", async () => {
                if (!refFile) return;
                const data = new FormData();
                data.append("audio", refFile);
                data.append("label", refName);
                data.append("transcript", refText);
                const response = await fetch("/api/references", {
                  method: "POST",
                  body: data,
                });
                const result = await response.json();
                if (!response.ok) throw new Error(result.detail);
                await refresh();
                edit("tts", "reference", result.id);
                setUpload(false);
                setToast("已导入；保存配置后应用");
              });
            }}
          >
            <h2>导入同一个人的参考音</h2>
            <p className="hint">
              推荐干净的8—15秒单声道人声，无背景音乐，并提供准确逐字转写。
            </p>
            <label>
              名称
              <input
                required
                value={refName}
                onChange={(e) => setRefName(e.target.value)}
              />
            </label>
            <label>
              音频文件
              <input
                required
                type="file"
                accept="audio/*"
                onChange={(e) => setRefFile(e.target.files?.[0])}
              />
            </label>
            <label>
              逐字转写
              <textarea
                required
                rows={4}
                value={refText}
                onChange={(e) => setRefText(e.target.value)}
              />
            </label>
            <div className="modal-actions">
              <button
                type="button"
                className="soft"
                onClick={() => setUpload(false)}
              >
                取消
              </button>
              <button className="primary" disabled={waiting}>
                导入参考音
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
