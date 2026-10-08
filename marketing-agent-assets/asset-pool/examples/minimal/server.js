// The smallest useful asset pool: serves a JSON file over the contract.
// Copy this file, point it at your own storage, and you're done -- the
// handler takes care of auth, filters, validation, and response shapes.
//
//   ASSET_POOL_TOKEN=change-me node examples/minimal/server.js
//   node bin/check.js http://127.0.0.1:8095 --token change-me
import { readFile } from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createAssetPoolHandler } from '../../src/index.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const assetsFile = process.env.ASSETS_FILE || path.join(here, 'assets.example.json');
const port = Number(process.env.PORT || 8095);

async function loadAssets() {
  return JSON.parse(await readFile(assetsFile, 'utf8'));
}

const matchesTag = (asset, tag) => {
  const needle = tag.toLowerCase();
  const tags = Array.isArray(asset.metadata?.tags) ? asset.metadata.tags : [];
  return tags.some((t) => String(t).toLowerCase() === needle)
    || String(asset.title || '').toLowerCase().includes(needle);
};

const handler = createAssetPoolHandler({
  token: process.env.ASSET_POOL_TOKEN,
  async listAssets({ kind, tag, limit }) {
    return (await loadAssets())
      .filter((asset) => !kind || asset.kind === kind)
      .filter((asset) => !tag || matchesTag(asset, tag))
      .slice(0, limit);
  },
  async getAsset(id) {
    return (await loadAssets()).find((asset) => asset.id === id) || null;
  }
});

export function createServer() {
  return http.createServer(handler);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  createServer().listen(port, '127.0.0.1', () => {
    console.log(`asset pool listening on http://127.0.0.1:${port}/api/assets`);
    if (!process.env.ASSET_POOL_TOKEN) {
      console.log('ASSET_POOL_TOKEN is not set: every request will be refused (500).');
    }
  });
}
