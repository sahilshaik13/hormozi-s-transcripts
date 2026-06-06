const CITATIONS_BLOCK_RE = /\n?---\s*\n📎\s*Sources used:[\s\S]*?(?:---\s*)?$/i;
const TRAILING_SOURCES_RE = /\n?📎\s*Sources used:[\s\S]*$/i;

export function stripAnswerCitations(text: string): string {
  let cleaned = text.trim();
  cleaned = cleaned.replace(CITATIONS_BLOCK_RE, "").trim();
  cleaned = cleaned.replace(TRAILING_SOURCES_RE, "").trim();
  cleaned = cleaned.replace(/\n---\s*$/, "").trim();
  return cleaned;
}

export function chunkSourceLabel(chunk: {
  note_title: string;
  note_type: string;
  note_path: string;
  source_videos?: string[];
  source_label?: string;
}): string {
  if (chunk.source_label) return chunk.source_label;
  if (chunk.source_videos?.length) return chunk.source_videos[0];
  const path = chunk.note_path.replace(/\\/g, "/");
  if (path.startsWith("07 Source Notes/")) {
    return path.split("/").pop()?.replace(/\.md$/i, "") ?? chunk.note_title;
  }
  return chunk.note_type.replace(/-/g, " ");
}
