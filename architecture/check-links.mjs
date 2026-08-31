// Architecture model drift guard.
//
// Walks every *.c4 file under architecture/ and checks that each relative
// `link` target still resolves to a real file or directory. A dead link means
// the model points at code that moved, was renamed, or was deleted — the most
// common way an architecture diagram goes stale without anyone noticing.
//
// URL and anchor links are skipped. Exits non-zero on any dead link so the
// Pages workflow fails before publishing a model that lies about the code.

import { readdirSync, readFileSync, existsSync } from "node:fs";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));

function c4Files(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = join(dir, e.name);
    if (e.isDirectory()) return e.name === "exports" ? [] : c4Files(p);
    return e.name.endsWith(".c4") ? [p] : [];
  });
}

const files = c4Files(root);
const linkRe = /\blink\s+("[^"]+"|'[^']+'|\S+)/g;
const missing = [];

for (const file of files) {
  const text = readFileSync(file, "utf8");
  for (const match of text.matchAll(linkRe)) {
    const target = match[1].replace(/^['"]|['"]$/g, "").split("#")[0];
    if (/^(https?:|mailto:|#)/.test(target)) continue;
    if (!/^\.\.?\//.test(target)) continue;
    if (!existsSync(resolve(dirname(file), target))) {
      missing.push(`${file} → ${target}`);
    }
  }
}

if (missing.length) {
  console.error(
    `✗ ${missing.length} dead source link(s) — the model points at code that no longer exists:`,
  );
  for (const entry of missing) console.error(`    ${entry}`);
  process.exit(1);
}

console.log(`✓ every architecture source link resolves (${files.length} .c4 files scanned).`);
