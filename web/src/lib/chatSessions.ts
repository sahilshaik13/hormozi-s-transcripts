import type { ChatMessage, Chunk } from "../types";

const STORAGE_KEY = "hormozi_chat_sessions_v1";
const MAX_SESSIONS = 40;

export type StoredChatSession = {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: ChatMessage[];
  sessionHits: Record<string, number>;
  domain: string;
};

export type ChatSessionStore = {
  activeSessionId: string;
  sessions: StoredChatSession[];
};

export function makeMessageId(): string {
  return `msg-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function newSessionId(): string {
  return `chat-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export function createEmptySession(): StoredChatSession {
  const now = Date.now();
  return {
    id: newSessionId(),
    title: "New chat",
    createdAt: now,
    updatedAt: now,
    messages: [],
    sessionHits: {},
    domain: "",
  };
}

function createDefaultStore(): ChatSessionStore {
  const session = createEmptySession();
  return { activeSessionId: session.id, sessions: [session] };
}

export function sessionTitleFromMessages(messages: ChatMessage[]): string {
  const first = messages.find((m) => m.role === "user");
  if (!first) return "New chat";
  const text = first.content.trim();
  if (!text) return "New chat";
  return text.length > 42 ? `${text.slice(0, 40)}…` : text;
}

export function loadStore(): ChatSessionStore {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return createDefaultStore();
    const parsed = JSON.parse(raw) as ChatSessionStore;
    if (!Array.isArray(parsed.sessions) || parsed.sessions.length === 0) {
      return createDefaultStore();
    }
    const activeExists = parsed.sessions.some((s) => s.id === parsed.activeSessionId);
    if (!activeExists) {
      parsed.activeSessionId = parsed.sessions[0].id;
    }
    return parsed;
  } catch {
    return createDefaultStore();
  }
}

export function saveStore(store: ChatSessionStore): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
}

export function getActiveSession(store: ChatSessionStore): StoredChatSession {
  return store.sessions.find((s) => s.id === store.activeSessionId) ?? store.sessions[0];
}

export function updateActiveSession(
  store: ChatSessionStore,
  patch: Partial<Pick<StoredChatSession, "messages" | "sessionHits" | "domain">>,
): ChatSessionStore {
  const now = Date.now();
  const sessions = store.sessions.map((s) => {
    if (s.id !== store.activeSessionId) return s;
    const messages = patch.messages ?? s.messages;
    return {
      ...s,
      ...patch,
      messages,
      title: sessionTitleFromMessages(messages),
      updatedAt: now,
    };
  });
  const next = { ...store, sessions };
  saveStore(next);
  return next;
}

export function switchActiveSession(store: ChatSessionStore, sessionId: string): ChatSessionStore {
  if (!store.sessions.some((s) => s.id === sessionId)) return store;
  const next = { ...store, activeSessionId: sessionId };
  saveStore(next);
  return next;
}

export function addNewSession(store: ChatSessionStore): ChatSessionStore {
  const session = createEmptySession();
  const sessions = [session, ...store.sessions].slice(0, MAX_SESSIONS);
  const next = { activeSessionId: session.id, sessions };
  saveStore(next);
  return next;
}

export function clearActiveSession(store: ChatSessionStore): ChatSessionStore {
  return updateActiveSession(store, { messages: [], sessionHits: {}, domain: "" });
}

export function deleteSession(store: ChatSessionStore, sessionId: string): ChatSessionStore {
  if (store.sessions.length <= 1) {
    return clearActiveSession(store);
  }
  const sessions = store.sessions.filter((s) => s.id !== sessionId);
  const activeSessionId =
    store.activeSessionId === sessionId ? sessions[0].id : store.activeSessionId;
  const next = { activeSessionId, sessions };
  saveStore(next);
  return next;
}

export function collectSessionChunks(messages: ChatMessage[]): Chunk[] {
  const chunks: Chunk[] = [];
  for (const m of messages) {
    if (m.role === "assistant" && m.chunks?.length) {
      chunks.push(...m.chunks);
    }
  }
  return chunks;
}

export function lastUserQuestion(messages: ChatMessage[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "user") return messages[i].content;
  }
  return "";
}
