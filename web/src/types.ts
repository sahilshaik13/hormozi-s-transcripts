export type GraphNode = {
  id: string;
  title: string;
  type: string;
  path: string;
  retrieved?: boolean;
  relevance?: number;
  hit_count?: number;
  snippet?: string;
};

export type GraphLink = {
  source: string;
  target: string;
  type: "wikilink" | "retrieval" | string;
  label?: string;
};

export type GraphData = {
  nodes: GraphNode[];
  links: GraphLink[];
  stats: {
    total_nodes: number;
    total_edges: number;
    retrieved?: number;
    question?: string;
  };
  typeColors?: Record<string, string>;
};

export type Chunk = {
  text: string;
  note_title: string;
  note_type: string;
  note_path: string;
  source_videos: string[];
  source_label?: string;
  relevance: number;
};

export type BrainStats = {
  vault_dir: string;
  index_dir: string;
  chunk_count: number;
  note_count: number;
  domains: string[];
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  chunks?: Chunk[];
};
