import { createSSRApp } from "vue";
import App from "./App.vue";
import { registerPrivacyAuthorizationHandler } from "./utils/privacy";

export function createApp() {
  registerPrivacyAuthorizationHandler();
  const app = createSSRApp(App);
  return { app };
}
