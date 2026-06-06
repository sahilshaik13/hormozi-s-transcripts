/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_HORMOZI_WEB_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
