// "Cozinha" o modelo IFC: transforma a geometria do IFC numa versão leve para o navegador.
// Usado em dois lugares, com o mesmo código:
//   - no build do Docker (cozinhar_modelo.mjs, em Node), que grava Labeee_gemeo.bin.gz;
//   - no navegador, como plano B, se o arquivo cozido não existir.
// O IFC tem 304 sólidos com superfícies curvas (NURBS) — as cadeiras, divisórias, armários.
// Transformar isso em triângulos leva ~1 min, por isso é feito uma vez só, no build.

export const VERSAO = 1;
const CELULA = 0.03;        // m — grade usada para simplificar peças com detalhe demais
const LIMITE_TRI = 1500;    // peças com mais triângulos que isso são simplificadas

export function ehInterativo(tipo, nm) {
  return (tipo === 'IFCFURNITURE' && /^Mesa \d\d$/.test(nm)) || (tipo === 'IFCWINDOW' && !!nm && !/fixa$/.test(nm)) ||
    (tipo === 'IFCDOOR' && !!nm) || tipo === 'IFCSENSOR' || tipo === 'IFCUNITARYEQUIPMENT' || tipo === 'IFCSPACE';
}

// agrupa os vértices numa grade de lado "cel" (simplificação por agrupamento de vértices)
function simplifica(pos, idx, cel) {
  const mapa = new Map(), soma = [], novo = new Uint32Array(pos.length / 3);
  for (let i = 0; i < pos.length / 3; i++) {
    const x = pos[3 * i], y = pos[3 * i + 1], z = pos[3 * i + 2];
    const k = Math.floor(x / cel) + ',' + Math.floor(y / cel) + ',' + Math.floor(z / cel);
    let j = mapa.get(k);
    if (j === undefined) { j = soma.length / 4; mapa.set(k, j); soma.push(0, 0, 0, 0); }
    soma[4 * j] += x; soma[4 * j + 1] += y; soma[4 * j + 2] += z; soma[4 * j + 3]++;
    novo[i] = j;
  }
  const n = soma.length / 4, p = new Float32Array(n * 3);
  for (let j = 0; j < n; j++) { const c = soma[4 * j + 3]; p[3 * j] = soma[4 * j] / c; p[3 * j + 1] = soma[4 * j + 1] / c; p[3 * j + 2] = soma[4 * j + 2] / c; }
  const t = [], vistos = new Set();
  for (let i = 0; i < idx.length; i += 3) {
    const a = novo[idx[i]], b = novo[idx[i + 1]], c = novo[idx[i + 2]];
    if (a === b || b === c || a === c) continue;
    const k = a < b ? (b < c ? a + ',' + b + ',' + c : a < c ? a + ',' + c + ',' + b : c + ',' + a + ',' + b)
                    : (a < c ? b + ',' + a + ',' + c : b < c ? b + ',' + c + ',' + a : c + ',' + b + ',' + a);
    if (vistos.has(k)) continue; vistos.add(k); t.push(a, b, c);
  }
  const ix = new Uint32Array(t);
  return { pos: p, nor: normais(p, ix), idx: ix };
}

function normais(p, ix) {
  const n = new Float32Array(p.length);
  for (let i = 0; i < ix.length; i += 3) {
    const a = 3 * ix[i], b = 3 * ix[i + 1], c = 3 * ix[i + 2];
    const ux = p[b] - p[a], uy = p[b + 1] - p[a + 1], uz = p[b + 2] - p[a + 2];
    const vx = p[c] - p[a], vy = p[c + 1] - p[a + 1], vz = p[c + 2] - p[a + 2];
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    for (const k of [a, b, c]) { n[k] += nx; n[k + 1] += ny; n[k + 2] += nz; }
  }
  for (let i = 0; i < n.length; i += 3) { const l = Math.hypot(n[i], n[i + 1], n[i + 2]) || 1; n[i] /= l; n[i + 1] /= l; n[i + 2] /= l; }
  return n;
}

// junta peças (cada uma com sua matriz 4x4, coluna por coluna) numa malha em coordenadas do mundo
function junta(pecas) {
  let nv = 0, ni = 0; for (const q of pecas) { nv += q.g.pos.length; ni += q.g.idx.length; }
  const P = new Float32Array(nv), N = new Int8Array(nv), I = nv / 3 > 65535 ? new Uint32Array(ni) : new Uint16Array(ni);
  let ov = 0, oi = 0;
  for (const { g, m } of pecas) {
    const { pos, nor, idx } = g, base = ov / 3;
    for (let i = 0; i < pos.length; i += 3) {
      const x = pos[i], y = pos[i + 1], z = pos[i + 2];
      P[ov + i] = m[0] * x + m[4] * y + m[8] * z + m[12];
      P[ov + i + 1] = m[1] * x + m[5] * y + m[9] * z + m[13];
      P[ov + i + 2] = m[2] * x + m[6] * y + m[10] * z + m[14];
      const a = nor[i], b = nor[i + 1], c = nor[i + 2];
      let nx = m[0] * a + m[4] * b + m[8] * c, ny = m[1] * a + m[5] * b + m[9] * c, nz = m[2] * a + m[6] * b + m[10] * c;
      const l = Math.hypot(nx, ny, nz) || 1;
      N[ov + i] = Math.round(127 * nx / l); N[ov + i + 1] = Math.round(127 * ny / l); N[ov + i + 2] = Math.round(127 * nz / l);
    }
    for (let i = 0; i < idx.length; i++) I[oi + i] = idx[i] + base;
    ov += pos.length; oi += idx.length;
  }
  return { pos: P, nor: N, idx: I };
}

// Lê o modelo aberto no web-ifc e devolve { meta, bufs } (malhas prontas, por material).
export function cozinhar(WebIFC, api, modelo) {
  const tipoDe = new Map();
  for (const t of ['IFCFURNITURE', 'IFCWINDOW', 'IFCDOOR', 'IFCSENSOR', 'IFCUNITARYEQUIPMENT', 'IFCSPACE', 'IFCROOF', 'IFCCOVERING', 'IFCSLAB']) {
    const ids = api.GetLineIDsWithType(modelo, WebIFC[t]);
    for (let i = 0; i < ids.size(); i++) tipoDe.set(ids.get(i), t);
  }
  const nomeDe = id => { try { const l = api.GetLine(modelo, id); return ((l.Name && l.Name.value) || '').trim(); } catch { return ''; } };

  const geoCache = new Map();
  const pegaGeo = (gid, escala) => {
    if (geoCache.has(gid)) return geoCache.get(gid);
    const geo = api.GetGeometry(modelo, gid);
    const v = api.GetVertexArray(geo.GetVertexData(), geo.GetVertexDataSize());
    const idx = new Uint32Array(api.GetIndexArray(geo.GetIndexData(), geo.GetIndexDataSize()));
    geo.delete();
    const nv = v.length / 6, pos = new Float32Array(nv * 3), nor = new Float32Array(nv * 3);
    for (let i = 0; i < nv; i++) for (let k = 0; k < 3; k++) { pos[3 * i + k] = v[6 * i + k]; nor[3 * i + k] = v[6 * i + 3 + k]; }
    const g = idx.length / 3 > LIMITE_TRI ? simplifica(pos, idx, CELULA / escala) : { pos, nor, idx };
    geoCache.set(gid, g); return g;
  };

  const materiais = [], matIdx = new Map();
  const material = c => {
    const cor = [c.x, c.y, c.z, c.w].map(v => Math.round(v * 100) / 100), k = cor.join();
    if (!matIdx.has(k)) { matIdx.set(k, materiais.length); materiais.push(cor); }
    return matIdx.get(k);
  };
  const estaticos = { base: new Map(), teto: new Map() }, objetos = [], lajes = [];
  const recebe = malha => {
    const id = malha.expressID, tipo = tipoDe.get(id) || 'OUTRO', nome = tipoDe.has(id) ? nomeDe(id) : '';
    const inter = ehInterativo(tipo, nome), porMat = new Map(), geos = malha.geometries;
    const laje = tipo === 'IFCSLAB' ? { pecas: [] } : null;
    for (let i = 0; i < geos.size(); i++) {
      const pg = geos.get(i), m = pg.flatTransformation;
      const escala = Math.hypot(m[0], m[1], m[2]) || 1;
      const mat = tipo === 'IFCSPACE' ? -1 : material(pg.color);
      const peca = { g: pegaGeo(pg.geometryExpressID, escala), m: Array.from(m), mat };
      if (laje) { laje.pecas.push(peca); continue; }
      const destino = inter ? porMat : estaticos[(tipo === 'IFCROOF' || tipo === 'IFCCOVERING') ? 'teto' : 'base'];
      if (!destino.has(mat)) destino.set(mat, []);
      destino.get(mat).push(peca);
    }
    if (laje) lajes.push(laje);
    if (inter) objetos.push({ id, tipo, nome, malhas: [...porMat].map(([mat, pecas]) => ({ mat, ...junta(pecas) })) });
  };
  api.StreamAllMeshes(modelo, recebe);
  api.StreamAllMeshesWithTypes(modelo, [WebIFC.IFCSPACE], recebe);   // salas não vêm por padrão

  // lajes: a do piso fica; as de cima (laje do telhado) vão para "teto", que não entra no modelo
  for (const l of lajes) { l.y = Infinity; for (const { g, m } of l.pecas) for (let i = 0; i < g.pos.length; i += 3) l.y = Math.min(l.y, m[1] * g.pos[i] + m[5] * g.pos[i + 1] + m[9] * g.pos[i + 2] + m[13]); }
  const piso = Math.min(...lajes.map(l => l.y));
  for (const l of lajes) for (const p of l.pecas) {
    const destino = estaticos[l.y > piso + 1.0 ? 'teto' : 'base'];
    if (!destino.has(p.mat)) destino.set(p.mat, []);
    destino.get(p.mat).push(p);
  }

  const bufs = [], ref = a => { bufs.push(a); return bufs.length - 1; };
  const malha = x => ({ mat: x.mat, pos: ref(x.pos), nor: ref(x.nor), idx: ref(x.idx) });
  const meta = {
    versao: VERSAO, materiais,
    // o teto (forro, telhado e laje de cima) fica de fora: só atrapalha a visão de cima
    estaticos: [...estaticos.base].map(([mat, pecas]) => ({ cat: 'base', ...malha({ mat, ...junta(pecas) }) })),
    objetos: objetos.map(o => ({ id: o.id, tipo: o.tipo, nome: o.nome, malhas: o.malhas.map(malha) })),
  };
  return { meta, bufs };
}

// ------------------------------------------------------------ arquivo binário: "GEMEO3D1" + tamanho do JSON + JSON + buffers
const TIPOS = { f32: Float32Array, i8: Int8Array, u16: Uint16Array, u32: Uint32Array };
const nomeTipo = a => a instanceof Float32Array ? 'f32' : a instanceof Int8Array ? 'i8' : a instanceof Uint16Array ? 'u16' : 'u32';

export function empacotar({ meta, bufs }) {
  let off = 0; const desc = [];
  for (const b of bufs) { desc.push([nomeTipo(b), off, b.length]); off += Math.ceil(b.byteLength / 4) * 4; }
  const json = new TextEncoder().encode(JSON.stringify({ ...meta, bufs: desc }));
  const cab = 12 + Math.ceil(json.length / 4) * 4;
  const out = new Uint8Array(cab + off);
  out.set(new TextEncoder().encode('GEMEO3D1'), 0);
  new DataView(out.buffer).setUint32(8, json.length, true);
  out.set(json, 12);
  bufs.forEach((b, i) => out.set(new Uint8Array(b.buffer, b.byteOffset, b.byteLength), cab + desc[i][1]));
  return out;
}

export function desempacotar(ab) {
  const u8 = new Uint8Array(ab);
  if (new TextDecoder().decode(u8.subarray(0, 8)) !== 'GEMEO3D1') throw new Error('arquivo do modelo inválido');
  const n = new DataView(ab).getUint32(8, true);
  const meta = JSON.parse(new TextDecoder().decode(u8.subarray(12, 12 + n)));
  const cab = 12 + Math.ceil(n / 4) * 4;
  const bufs = meta.bufs.map(([t, o, len]) => new TIPOS[t](ab, cab + o, len));
  return { meta, bufs };
}
