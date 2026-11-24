// Roda no build do Docker: lê o IFC, "cozinha" a geometria e grava um .bin.gz leve para o navegador.
// Uso: node cozinhar_modelo.mjs <entrada.ifc> <saida.bin.gz>
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { gzipSync } from 'node:zlib';
import { cozinhar, empacotar } from './cozinhar.mjs';

const require = createRequire(import.meta.url);
const WebIFC = require('web-ifc');
const [entrada, saida] = process.argv.slice(2);
const t0 = Date.now();
const api = new WebIFC.IfcAPI();
await api.Init();
const modelo = api.OpenModel(new Uint8Array(readFileSync(entrada)), { COORDINATE_TO_ORIGIN: true });
const res = cozinhar(WebIFC, api, modelo);
api.CloseModel(modelo);
const bin = empacotar(res);
const gz = gzipSync(bin, { level: 9 });
writeFileSync(saida, gz);
let tri = 0;
for (const m of [...res.meta.estaticos, ...res.meta.objetos.flatMap(o => o.malhas)]) tri += res.bufs[m.idx].length / 3;
console.log(`modelo cozido: ${res.meta.objetos.length} objetos com sensor, ${Math.round(tri / 1000)} mil triângulos, ` +
  `${(gz.length / 1e6).toFixed(1)} MB, ${Math.round((Date.now() - t0) / 1000)} s`);
