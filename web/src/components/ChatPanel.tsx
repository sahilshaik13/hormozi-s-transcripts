import { FormEvent, useEffect, useRef, useState } from "react";
import { chunkSourceLabel } from "../lib/formatAnswer";
import type { ChatMessage, Chunk } from "../types";
import { AnswerContent } from "./AnswerContent";

type SessionItem = { id: string; title: string; updatedAt: number };

type Props = {
  open: boolean;
  onToggle: () => void;
  stats: { chunk_count: number; note_count: number; domains: string[] } | null;
  loading: boolean;
  messages: ChatMessage[];
  domain: string;
  sessions: SessionItem[];
  activeSessionId: string;
  onDomainChange: (d: string) => void;
  onAsk: (question: string) => void;
  onNewSession: () => void;
  onSwitchSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
  onClear: () => void;
  onChunkClick: (chunk: Chunk) => void;
};

const STARTERS = [
  "How do I price my offer?",
  "What's the CLOSER framework?",
  "How do I get more leads?",
  "Mindset for scaling past $1M",
];

export function ChatPanel({
  open,
  onToggle,
  stats,
  loading,
  messages,
  domain,
  sessions,
  activeSessionId,
  onDomainChange,
  onAsk,
  onNewSession,
  onSwitchSession,
  onDeleteSession,
  onClear,
  onChunkClick,
}: Props) {
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  useEffect(() => {
    if (open) textareaRef.current?.focus();
  }, [open]);

  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (loading) return;
    const q = input.trim();
    if (!q) {
      textareaRef.current?.focus();
      return;
    }
    onAsk(q);
    setInput("");
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  if (!open) {
    return (
      <button type="button" className="chat-fab-fixed" onClick={onToggle} title="Open Ask Hormozi">
        <span className="chat-fab-icon">🧠</span>
        <span className="chat-fab-label">Ask Hormozi</span>
      </button>
    );
  }

  return (
    <aside className="chat-panel-fixed">
      <header className="chat-header">
        <div className="chat-header-top">
          <div>
            <h1>Ask Hormozi</h1>
            <p className="chat-subtitle">RAG chat · answers from your vault</p>
          </div>
          <div className="chat-header-actions">
            <button type="button" className="icon-btn" onClick={onClear} title="Clear chat" disabled={loading || messages.length === 0}>
              ↺
            </button>
            <button type="button" className="icon-btn" onClick={onToggle} title="Collapse panel">
              →
            </button>
          </div>
        </div>
        {stats && (
          <p className="stats">
            {stats.chunk_count} chunks · {stats.note_count} notes
          </p>
        )}
      </header>

      <div className="session-bar">
        <button type="button" className="session-new-btn" onClick={onNewSession} disabled={loading}>
          + New chat
        </button>
        <label className="session-select">
          <span className="sr-only">Chat session</span>
          <select
            value={activeSessionId}
            onChange={(e) => onSwitchSession(e.target.value)}
            disabled={loading}
          >
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title}
              </option>
            ))}
          </select>
        </label>
        {sessions.length > 1 && (
          <button
            type="button"
            className="icon-btn session-delete-btn"
            onClick={() => onDeleteSession(activeSessionId)}
            title="Delete this chat"
            disabled={loading}
          >
            ×
          </button>
        )}
      </div>

      {stats && stats.domains.length > 0 && (
        <label className="domain-select">
          Domain filter
          <select value={domain} onChange={(e) => onDomainChange(e.target.value)}>
            <option value="">All domains</option>
            {stats.domains.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
      )}

      <div className="messages">
        {messages.length === 0 && !loading && (
          <div className="chat-welcome">
            <p>Ask Alex Hormozi anything. He answers from your extracted brain — cited, direct, no fluff.</p>
            <p className="chat-welcome-hint">
              Each question is independent — no memory between asks. Retrieved notes light up purple on the graph.
            </p>
            <div className="starters">
              {STARTERS.map((s) => (
                <button key={s} type="button" className="starter-chip" disabled={loading} onClick={() => onAsk(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) => (
          <div key={m.id} className={`bubble-row ${m.role}`}>
            {m.role === "assistant" && <div className="avatar">AH</div>}
            <div className={`bubble ${m.role}`}>
              <div className="bubble-content">
                {m.role === "assistant" ? <AnswerContent content={m.content} /> : m.content}
              </div>
              {m.chunks && m.chunks.length > 0 && (
                <div className="bubble-sources">
                  <span className="sources-label">Sources</span>
                  <div className="source-chips">
                    {m.chunks.map((c, i) => (
                      <button
                        key={`${c.note_path}-${i}`}
                        type="button"
                        className="source-chip"
                        onClick={() => onChunkClick(c)}
                        title={c.note_path}
                      >
                        <span className="chip-header">
                          <span className="chip-title">{c.note_title}</span>
                          <span className="chip-rel">{(c.relevance * 100).toFixed(0)}%</span>
                        </span>
                        <span className="chip-meta">
                          {c.note_type.replace(/-/g, " ")} · {chunkSourceLabel(c)}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div className="bubble-row assistant">
            <div className="avatar">AH</div>
            <div className="bubble assistant loading-bubble">
              <span className="typing">
                <span />
                <span />
                <span />
              </span>
              Searching brain…
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <form className="chat-form" onSubmit={submit}>
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="What would Hormozi say about…"
          rows={2}
          disabled={loading}
        />
        <div className="chat-form-footer">
          <span className="enter-hint">Enter to send · Shift+Enter newline</span>
          <button type="submit" disabled={loading}>
            Ask
          </button>
        </div>
      </form>
    </aside>
  );
}
