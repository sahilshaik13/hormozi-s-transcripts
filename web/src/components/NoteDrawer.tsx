import { useEffect, useState } from "react";
import { fetchNote } from "../lib/api";
import type { GraphNode } from "../types";

type Props = {
  node: GraphNode | null;
  chatOpen: boolean;
  onClose: () => void;
};

export function NoteDrawer({ node, chatOpen, onClose }: Props) {
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const notePath = node?.path || node?.id || "";

  useEffect(() => {
    if (!node) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [node, onClose]);

  useEffect(() => {
    if (!node) {
      setContent(null);
      return;
    }
    if (!notePath || notePath === "__query__") {
      setContent(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setContent(null);
    fetchNote(notePath)
      .then((n) => setContent(n.content))
      .catch((e) => setContent(`Error: ${e.message}`))
      .finally(() => setLoading(false));
  }, [node, notePath]);

  if (!node) return null;

  return (
    <>
      <button
        type="button"
        className="note-drawer-backdrop"
        onClick={onClose}
        aria-label="Close note panel"
      />
      <aside
        className={`note-drawer ${chatOpen ? "chat-open" : "chat-closed"}`}
        role="dialog"
        aria-labelledby="note-drawer-title"
      >
        <div className="note-drawer-header">
          <div className="note-drawer-heading">
            <h2 id="note-drawer-title">{node.title}</h2>
            <div className="note-meta">
              <span className="note-type">{node.type}</span>
              {node.relevance != null && node.relevance > 0 && (
                <span className="note-relevance">
                  {(node.relevance * 100).toFixed(0)}% match
                </span>
              )}
            </div>
          </div>
          <button type="button" className="close-btn" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        {node.snippet && (
          <details className="note-snippet">
            <summary>Retrieved excerpt</summary>
            <p>{node.snippet}</p>
          </details>
        )}
        <div className="note-body">
          {loading && <p className="note-status">Loading note…</p>}
          {!loading && notePath && notePath !== "__query__" && content === null && (
            <p className="note-empty">Could not load this note.</p>
          )}
          {!loading && (!notePath || notePath === "__query__") && (
            <p className="note-empty">This node has no vault note (e.g. search query).</p>
          )}
          {!loading && content !== null && <pre>{content}</pre>}
        </div>
      </aside>
    </>
  );
}
