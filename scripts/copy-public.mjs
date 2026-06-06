import { cpSync, existsSync, rmSync } from "node:fs";
import { resolve } from "node:path";

const dist = resolve("web/dist");
const pub = resolve("public");

if (!existsSync(dist)) {
  console.error("Missing web/dist — run: npm run build --prefix web");
  process.exit(1);
}

rmSync(pub, { recursive: true, force: true });
cpSync(dist, pub, { recursive: true });
console.log("Copied web/dist → public/");
