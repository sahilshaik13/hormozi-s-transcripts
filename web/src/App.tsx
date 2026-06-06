import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { askBrain, fetchGraph, fetchStats, getToken, highlightGraph, setToken } from "./lib/api";
import {
  addNewSession,
  clearActiveSession,
  collectSessionChunks,
  deleteSession,
  getActiveSession,
  lastUserQuestion,
  loadStore,
  makeMessageId,
  switchActiveSession,
  updateActiveSession,
  type ChatSessionStore,
} from "./lib/chatSessions";
import { BrainGraph } from "./components/BrainGraph";
import { ChatPanel } from "./components/ChatPanel";
import { NoteDrawer } from "./components/NoteDrawer";
import type { ChatMessage, Chunk, GraphData, GraphNode } from "./types";
import "./App.css";

export default function App() {
  const [authNeeded, setAuthNeeded] = useState(false);
  const [tokenInput, setTokenInput] = useState(getToken());
  const [stats, setStats] = useState<Awaited<ReturnType<typeof fetchStats>> | null>(null);
  const [baseGraph, setBaseGraph] = useState<GraphData | null>(null);
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [store, setStore] = useState<ChatSessionStore>(() => loadStore());
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(true);
  const skipGraphRestore = useRef(false);

  const activeSession = useMemo(() => getActiveSession(store), [store]);
  const messages = activeSession.messages;
  const sessionHits = activeSession.sessionHits;
  const domain = activeSession.domain;

  const applySessionGraph = useCallback(
    async (sessionMessages: ChatMessage[], hits: Record<string, number>) => {
      if (!baseGraph) return;
      const chunks = collectSessionChunks(sessionMessages);
      if (chunks.length === 0 && Object.keys(hits).length === 0) {
        setGraph(baseGraph);
        return;
      }
      try {
        const highlighted = await highlightGraph(
          chunks,
          hits,
          lastUserQuestion(sessionMessages),
        );
        setGraph(highlighted);
      } catch {
        setGraph(baseGraph);
      }
    },
    [baseGraph],
  );

  const loadBase = useCallback(async () => {
    const [s, g] = await Promise.all([fetchStats(), fetchGraph()]);
    setStats(s);
    setBaseGraph(g);
    setGraph(g);
    setAuthNeeded(false);
    setError(null);
    return g;
  }, []);

  useEffect(() => {
    loadBase()
      .then((g) => {
        const session = getActiveSession(loadStore());
        const chunks = collectSessionChunks(session.messages);
        if (chunks.length > 0 || Object.keys(session.sessionHits).length > 0) {
          return highlightGraph(chunks, session.sessionHits, lastUserQuestion(session.messages))
            .then(setGraph)
            .catch(() => setGraph(g));
        }
      })
      .catch((e) => {
        if (String(e.message).includes("401") || String(e.message).includes("Unauthorized")) {
          setAuthNeeded(true);
        } else {
          setError(e.message);
        }
      });
  }, [loadBase]);

  useEffect(() => {
    if (skipGraphRestore.current) {
      skipGraphRestore.current = false;
      return;
    }
    const session = getActiveSession(store);
    applySessionGraph(session.messages, session.sessionHits);
  }, [store.activeSessionId, applySessionGraph]);

  function patchSession(
    patch: Partial<Pick<typeof activeSession, "messages" | "sessionHits" | "domain">>,
  ) {
    setStore((prev) => updateActiveSession(prev, patch));
  }

  function bumpHits(chunks: Chunk[], prev: Record<string, number>) {
    const next = { ...prev };
    for (const c of chunks) {
      const pathId = c.note_path.replace(/\\/g, "/").trim();
      if (pathId) next[pathId] = (next[pathId] ?? 0) + 1;
      if (c.note_title) next[c.note_title] = (next[c.note_title] ?? 0) + 1;
    }
    return next;
  }

  async function handleAsk(question: string) {
    setLoading(true);
    setError(null);
    setChatOpen(true);
    const userMsg: ChatMessage = { id: makeMessageId(), role: "user", content: question };
    const withUser = [...messages, userMsg];
    patchSession({ messages: withUser });
    try {
      const res = await askBrain(question, domain || null, []);
      const assistantMsg: ChatMessage = {
        id: makeMessageId(),
        role: "assistant",
        content: res.answer,
        chunks: res.chunks,
      };
      const nextHits = bumpHits(res.chunks, sessionHits);
      patchSession({ messages: [...withUser, assistantMsg], sessionHits: nextHits });
      setGraph(res.graph);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      const errMsg: ChatMessage = {
        id: makeMessageId(),
        role: "assistant",
        content: `Error: ${e instanceof Error ? e.message : String(e)}`,
      };
      patchSession({ messages: [...withUser, errMsg] });
    } finally {
      setLoading(false);
    }
  }

  function handleSelectNode(node: GraphNode | null) {
    if (!node) {
      setSelected(null);
      return;
    }
    const fresh = graph?.nodes.find((n) => n.id === node.id) ?? node;
    setSelected(fresh);
  }

  function handleChunkClick(chunk: Chunk) {
    const pathId = chunk.note_path.replace(/\\/g, "/").trim();
    const node =
      graph?.nodes.find(
        (n) => n.id === pathId || n.path === pathId || n.title === chunk.note_title,
      ) ?? null;
    if (node) handleSelectNode(node);
  }

  function saveToken() {
    setToken(tokenInput.trim());
    loadBase();
  }

  function handleNewSession() {
    skipGraphRestore.current = true;
    setStore((prev) => addNewSession(prev));
    if (baseGraph) setGraph(baseGraph);
    setSelected(null);
  }

  function handleSwitchSession(sessionId: string) {
    if (sessionId === store.activeSessionId) return;
    setStore((prev) => switchActiveSession(prev, sessionId));
    setSelected(null);
  }

  function handleClearChat() {
    skipGraphRestore.current = true;
    setStore((prev) => clearActiveSession(prev));
    if (baseGraph) setGraph(baseGraph);
    setSelected(null);
  }

  function handleDeleteSession(sessionId: string) {
    setSelected(null);
    setStore((prev) => deleteSession(prev, sessionId));
  }

  function handleDomainChange(value: string) {
    patchSession({ domain: value });
  }

  if (authNeeded) {
    return (
      <div className="auth-screen">
        <div className="auth-card">
          <h1>🧠 Hormozi Brain</h1>
          <p>Enter your private access token (HORMOZI_WEB_TOKEN).</p>
          <input
            type="password"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            placeholder="Bearer token"
          />
          <button type="button" onClick={saveToken}>
            Connect
          </button>
        </div>
      </div>
    );
  }

  const sessionList = store.sessions
    .slice()
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .map((s) => ({ id: s.id, title: s.title, updatedAt: s.updatedAt }));

  return (
    <div
      className={`app ${chatOpen ? "chat-open" : "chat-closed"}${selected ? " note-open" : ""}`}
    >
      <main className="graph-area">
        {error && (
          <div className="error-banner">
            {error}
            <button type="button" className="error-dismiss" onClick={() => setError(null)}>
              ×
            </button>
          </div>
        )}
        {graph ? (
          <BrainGraph
            graph={graph}
            sessionHits={sessionHits}
            selectedId={selected?.id ?? null}
            onSelect={handleSelectNode}
          />
        ) : (
          <div className="loading-graph">
            <span className="loading-graph-spinner" />
            Loading knowledge graph…
          </div>
        )}
      </main>
      <NoteDrawer
        node={selected}
        chatOpen={chatOpen}
        onClose={() => setSelected(null)}
      />
      <ChatPanel
        open={chatOpen}
        onToggle={() => setChatOpen((open) => !open)}
        stats={stats}
        loading={loading}
        messages={messages}
        domain={domain}
        sessions={sessionList}
        activeSessionId={store.activeSessionId}
        onDomainChange={handleDomainChange}
        onAsk={handleAsk}
        onNewSession={handleNewSession}
        onSwitchSession={handleSwitchSession}
        onDeleteSession={handleDeleteSession}
        onClear={handleClearChat}
        onChunkClick={handleChunkClick}
      />
    </div>
  );
}
