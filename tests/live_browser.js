// Headless-browser check of the read-only live page (optional; needs Chrome + `npm i puppeteer-core`).
//   node tests/live_browser.js <base_url> <data_dir> <map_id> <out_dir>
// Changes bot states through scripts/tamap_cli.sh, waits for each to reach the page over SSE, saves a
// screenshot per step, and checks that the canvas sprites match sprites.bot_pixels cell by cell (DPR 1 and 2).
const puppeteer = require("puppeteer-core");
const {execFileSync} = require("child_process");
const path = require("path");

const [base, dataDir, mapId, outDir] = process.argv.slice(2);
const ROOT = path.resolve(__dirname, "..");
const CHROME = process.env.CHROME || "/usr/local/bin/google-chrome";
const setStatus = args => execFileSync(path.join(ROOT, "scripts", "tamap_cli.sh"),
  ["set_bot_status", JSON.stringify({map_id: mapId, ...args})],
  {env: {...process.env, TAMAP_DATA_DIR: dataDir}, stdio: ["ignore", "ignore", "ignore"]});
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function spriteMismatches(page, bot, dpr) {
  return page.evaluate(async (bot, dpr) => {
    const S = await (await fetch("/api/scene" + location.search)).json();
    const ctx = document.getElementById("c").getContext("2d");
    const node = S.nodes.find(n => n[0] === bot), st = JSON.parse(JSON.stringify(window.__snapStatus || {}))[bot];
    const cells = new Map();
    for (const [gx, gy, c] of S.sprites[bot][st]) cells.set(gx + "," + gy, c);
    const x0 = node[2] - 8 * S.scale, y0 = S.sprite_y, bad = [];
    for (const [k, c] of cells) {
      const [gx, gy] = k.split(",").map(Number);
      const px = Math.floor((x0 + gx * S.scale + S.scale / 2) * dpr), py = Math.floor((y0 + gy * S.scale + S.scale / 2) * dpr);
      const d = ctx.getImageData(px, py, 1, 1).data;
      const hex = "#" + [d[0], d[1], d[2]].map(v => v.toString(16).padStart(2, "0")).join("");
      if (hex !== c) bad.push([gx, gy, c, hex]);
    }
    return {checked: cells.size, bad};
  }, bot, dpr);
}

(async () => {
  const browser = await puppeteer.launch({executablePath: CHROME, args: ["--no-sandbox"]});
  const errors = [], results = [];
  const page = await browser.newPage();
  page.on("pageerror", e => errors.push(String(e)));
  page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
  await page.setViewport({width: 1000, height: 820, deviceScaleFactor: 1});
  await page.goto(`${base}/live/${mapId}`, {waitUntil: "domcontentloaded"});
  await page.waitForFunction(() => document.getElementById("connText").textContent === "ライブ", {timeout: 10000});
  await page.screenshot({path: `${outDir}/live_00_initial.png`});
  const steps = [
    ["01_pm_reception", {bot: "pm", status: "working", note: "依頼を受付", say: "まかせてください！"}, 1000],
    ["02_ma_working_envelope", {bot: "map_architect", status: "working", note: "T1〜T7を構造化中", say: "線、7本つなぐっす。"}, 450],
    ["03_ma_done", {bot: "map_architect", status: "done", note: "7タスク・7依存", say: "地図、できたっす！"}, 1000],
    ["04_ra_working", {bot: "risk_analyst", status: "working", note: "T4遅延の波及を分析", say: "T4、あやしいかも…"}, 1000],
    ["05_qr_error", {bot: "quality_reviewer", status: "error", note: "60秒応答なし"}, 1000],
  ];
  for (const [name, args, wait] of steps) {
    const before = await page.evaluate(() => document.body.dataset.lastEvent);
    const t0 = Date.now();
    setStatus(args);
    await page.waitForFunction(b => document.body.dataset.lastEvent !== b, {timeout: 5000}, before);
    results.push({step: name, cli_plus_push_ms: Date.now() - t0});
    await sleep(wait);
    await page.screenshot({path: `${outDir}/live_${name}.png`});
  }
  const pixel = [];
  for (const dpr of [1, 2]) {
    const p = dpr === 1 ? page : await browser.newPage();
    if (dpr !== 1) {
      await p.setViewport({width: 1000, height: 820, deviceScaleFactor: dpr});
      await p.goto(`${base}/live/${mapId}`, {waitUntil: "domcontentloaded"});
      await p.waitForFunction(() => document.getElementById("connText").textContent === "ライブ", {timeout: 10000});
      await sleep(300);
    }
    await p.evaluate(async () => {
      const s = await (await fetch(`/api/maps/${location.pathname.split("/").pop()}` + location.search)).json();
      window.__snapStatus = Object.fromEntries(Object.entries(s.bots).map(([k, v]) => [k, v.status]));
    });
    for (const bot of ["map_architect", "quality_reviewer"])  // done / error: not bobbing, no glow
      pixel.push({dpr, bot, ...(await spriteMismatches(p, bot, dpr))});
  }
  const ok = errors.length === 0 && pixel.every(x => x.bad.length === 0);
  console.log(JSON.stringify({ok, results, pixel: pixel.map(x => ({dpr: x.dpr, bot: x.bot, checked: x.checked,
    mismatches: x.bad.length, sample: x.bad.slice(0, 3)})), errors}, null, 1));
  await browser.close();
  process.exit(ok ? 0 : 1);
})().catch(e => { console.error(e); process.exit(1); });
