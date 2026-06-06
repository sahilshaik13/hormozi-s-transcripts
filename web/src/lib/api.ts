import type { BrainStats, Chunk, GraphData } from "../types";

const TOKEN_KEY = "hormozi_web_token";

/** Empty = same-origin (/api). Set VITE_API_BASE_URL only for split-host deploys. */
const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";

export function getToken(): string {
  const stored = localStorage.getItem(TOKEN_KEY);
  if (stored) return stored;
  return (import.meta.env.VITE_HORMOZI_WEB_TOKEN as string | undefined)?.trim() ?? "";
}

export function setToken(token: string) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string>),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || res.statusText);
  }
  return res.json() as Promise<T>;
}

export async function fetchStats(): Promise<BrainStats> {
  return api("/api/stats");
}

export async function fetchGraph(): Promise<GraphData> {
  return api("/api/graph");
}

export async function highlightGraph(
  chunks: Chunk[],
  sessionHits: Record<string, number>,
  question = "",
): Promise<GraphData> {
  return api("/api/graph/highlight", {
    method: "POST",
    body: JSON.stringify({
      chunks,
      question,
      session_hits: sessionHits,
    }),
  });
}

export async function askBrain(
  question: string,
  domain: string | null,
  history: { role: string; content: string }[],
): Promise<{ answer: string; chunks: Chunk[]; graph: GraphData; question: string }> {
  return api("/api/ask", {
    method: "POST",
    body: JSON.stringify({ question, domain, history }),
  });
}

export async function searchBrain(
  query: string,
  domain: string | null,
): Promise<{ chunks: Chunk[]; graph: GraphData; query: string }> {
  return api("/api/search", {
    method: "POST",
    body: JSON.stringify({ query, domain }),
  });
}

export async function fetchNote(path: string): Promise<{ path: string; title: string; content: string }> {
  return api(`/api/note?path=${encodeURIComponent(path)}`);
}
