import { writeFileSync } from "node:fs";

// Wrangler --env-file supplies Worker bindings; inherited Node environment
// variables alone do not supply these application secrets to the Worker.
const defaults = {
  RASPBERRY_PI_BASE_URL: "http://host.docker.internal:5000",
  RASPBERRY_PI_DEVICE_TOKEN: "",
};
const lines = Object.entries(defaults).map(([key, fallback]) => {
  const value = process.env[key] ?? fallback;
  if (/[\r\n\0]/.test(value)) throw new Error(`${key} must be a single-line value.`);
  // dotenv double quotes preserve #, spaces and single quotes literally.
  if (value.includes('"')) throw new Error(`${key} must not contain double quotes.`);
  return `${key}="${value}"`;
});
writeFileSync(new URL("../.env", import.meta.url), "", { mode: 0o600 });
writeFileSync(new URL("../.env.local", import.meta.url), `${lines.join("\n")}\n`, { mode: 0o600 });
process.argv = [process.execPath, "scripts/run-dual.mjs", "start"];
await import("../scripts/run-dual.mjs");
