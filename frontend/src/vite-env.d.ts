/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  // Phase A2: silent dev-token sign-in (user-facing login disabled). The app
  // swaps this fixed code for a real server-minted token on load.
  readonly VITE_DEV_LOGIN_CODE?: string;
  // Set to "true" to re-enable the legacy token/dev-code login screen.
  readonly VITE_ENABLE_LOGIN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
