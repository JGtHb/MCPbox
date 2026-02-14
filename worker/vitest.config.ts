import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  test: {
    globals: true,
    environment: "node",
    include: ["src/**/*.test.ts"],
    server: {
      deps: {
        // Inline these so vitest handles their imports (including cloudflare: protocol)
        inline: [/@cloudflare\/workers-oauth-provider/],
      },
    },
  },
  resolve: {
    alias: {
      // Stub cloudflare:workers for testing outside Workers runtime
      "cloudflare:workers": path.resolve(
        __dirname,
        "src/__mocks__/cloudflare-workers.ts"
      ),
    },
  },
});
