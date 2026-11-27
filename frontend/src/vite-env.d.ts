/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "true" → serve in-memory fixtures instead of calling the backend. */
  readonly VITE_USE_MOCKS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
