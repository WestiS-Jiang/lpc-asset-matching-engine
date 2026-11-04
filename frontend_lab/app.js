const CATEGORY_ORDER = ["body", "hair", "armor", "weapons"];
const BODY_KEYS = ["male", "female", "teen", "child", "muscular", "pregnant"];
const ANIMATION_ALIASES = {
  combat: "combat_idle",
  "1h_slash": "backslash",
  "1h_backslash": "backslash",
  "1h_halfslash": "halfslash",
};
const COLOR_FAMILIES = {
  navy: {
    aliases: ["海军", "海军蓝", "navy", "marine"],
    tokenPreferences: ["navy", "blue", "teal", "sky", "cyan"],
  },
  pink: {
    aliases: ["粉", "粉色", "pink", "rose", "fuchsia", "magenta"],
    tokenPreferences: ["pink", "rose", "lavender", "purple", "magenta"],
  },
  ice_blue: {
    aliases: ["寒冰", "冰蓝", "冰霜", "霜蓝", "冰", "ice", "icy", "frost", "glacier"],
    tokenPreferences: ["ice", "iceblue", "whitecyan", "sky", "cyan", "blue", "teal", "navy"],
  },
  black: {
    aliases: ["黑", "黑色", "black", "dark", "shadow"],
    tokenPreferences: ["black", "charcoal", "dark gray", "darkgray", "raven", "slate", "gray"],
  },
  red: {
    aliases: ["红", "红色", "赤", "red", "crimson", "scarlet", "ruby"],
    tokenPreferences: ["red", "darkred", "ruby", "redhead", "carrot", "ginger", "strawberry", "maroon"],
  },
  blue: {
    aliases: ["蓝", "蓝色", "blue", "azure", "cyan"],
    tokenPreferences: ["blue", "sky", "teal", "navy", "cyan"],
  },
  green: {
    aliases: ["绿", "绿色", "green", "emerald", "forest"],
    tokenPreferences: ["green", "forest", "olive", "teal"],
  },
  purple: {
    aliases: ["紫", "紫色", "purple", "violet", "lavender"],
    tokenPreferences: ["purple", "violet", "lavender", "rose"],
  },
  gold: {
    aliases: ["金", "金色", "黄", "黄色", "gold", "yellow", "amber"],
    tokenPreferences: ["gold", "yellow", "amber", "orange", "tan"],
  },
  white: {
    aliases: ["白", "白色", "银", "银色", "white", "silver", "platinum"],
    tokenPreferences: ["white", "whiteblonde", "platinum", "gray", "light"],
  },
  brown: {
    aliases: ["棕", "棕色", "褐", "brown", "tan", "leather"],
    tokenPreferences: ["brown", "light brown", "dark brown", "chestnut", "walnut", "tan", "leather"],
  },
};
const SLOT_KEYWORDS = {
  hair: ["头发", "发色", "短发", "长发", "hair", "hairstyle", "ponytail"],
  armor: ["轻甲", "重甲", "护甲", "盔甲", "armor", "armour", "mail", "plate", "leather", "skirt", "dress", "uniform", "blouse", "kimono"],
  hat: ["帽", "帽子", "鸭舌帽", "头盔", "hat", "cap", "helmet", "hood"],
  weapons: ["剑", "武器", "刀", "枪", "斧", "锤", "双截棍", "weapon", "sword", "axe", "spear", "staff", "flail"],
  body: ["肤色", "皮肤", "skin", "skintone"],
  feet: ["鞋", "靴", "鞋子", "shoe", "shoes", "sneaker", "boot", "boots", "sandals", "slipper"],
  legs: ["裤", "裙", "shorts", "pants", "leggings", "skirt"],
  torso: ["上衣", "外套", "clothes", "shirt", "blouse", "dress", "uniform", "kimono"],
};

const state = {
  latestAnalyze: null,
  currentSelectedLayers: { body: null, hair: null, armor: null, weapons: null },
  currentExtendedLayers: {},
  colorIntent: {},
  resolvedColorTokens: {},
  lastLpcUrl: "",
  lastResolvedHash: "",
};

const els = {
  backendUrl: document.getElementById("backendUrl"),
  bodyType: document.getElementById("bodyType"),
  promptInput: document.getElementById("promptInput"),
  genMode: document.getElementById("genMode"),
  maxTasks: document.getElementById("maxTasks"),
  analyzeBtn: document.getElementById("analyzeBtn"),
  executeBtn: document.getElementById("executeBtn"),
  statusText: document.getElementById("statusText"),
  summaryBox: document.getElementById("summaryBox"),
  provenanceBody: document.querySelector("#provenanceTable tbody"),
  missingAssets: document.getElementById("missingAssets"),
  executeResult: document.getElementById("executeResult"),
  syncLpcBtn: document.getElementById("syncLpcBtn"),
  openLpcBtn: document.getElementById("openLpcBtn"),
  lpcIframe: document.getElementById("lpcIframe"),
};

els.promptInput.value = "一个使用双截棍的轻甲战士，短发，人类男性";

function normalizeBaseUrl(url) {
  return url.trim().replace(/\/+$/, "");
}

function toBackendOrigin(url) {
  const normalized = normalizeBaseUrl(url);
  try {
    return new URL(normalized).origin;
  } catch (_err) {
    return normalized;
  }
}

function encodeHashParams(params) {
  return Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null && String(value) !== "")
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
    .join("&");
}

function getGenModeEnabled() {
  return els.genMode.value === "on";
}

function inferBodyTypeFromPrompt(promptText) {
  const text = String(promptText || "").toLowerCase();
  if (!text) return null;
  if (/女性|女生|女孩|少女|woman|female|girl/.test(text)) return "female";
  if (/男性|男生|男孩|man|male|boy/.test(text)) return "male";
  return null;
}

function autoSyncBodyTypeByPrompt(promptText) {
  const inferred = inferBodyTypeFromPrompt(promptText);
  if (!inferred) return null;
  if (els.bodyType.value === inferred) return null;
  els.bodyType.value = inferred;
  return inferred;
}

function updateGenUi() {
  const enabled = getGenModeEnabled();
  els.executeBtn.disabled = !enabled;
}

function variantToFilename(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "_");
}

function getLayerEntries(meta) {
  const entries = [];
  for (let idx = 1; idx < 20; idx += 1) {
    const layer = meta.layers?.[`layer_${idx}`];
    if (!layer) break;
    entries.push(layer);
  }
  return entries;
}

function canonicalColorToken(token) {
  return String(token || "")
    .trim()
    .toLowerCase()
    .replace(/[_\-\s]+/g, "");
}

function pickColorFamilyInSegment(segment) {
  const text = String(segment || "").toLowerCase();
  let best = null;
  for (const [family, cfg] of Object.entries(COLOR_FAMILIES)) {
    for (const alias of cfg.aliases) {
      const idx = text.indexOf(String(alias).toLowerCase());
      if (idx < 0) continue;
      if (!best || idx < best.index) {
        best = { family, index: idx };
      }
    }
  }
  return best?.family || null;
}

function extractColorIntent(promptText) {
  const prompt = String(promptText || "").trim();
  if (!prompt) return {};

  const intent = {};
  const segments = prompt.split(/[，,。；;！!？?\n]+/).map((x) => x.trim()).filter(Boolean);

  for (const segment of segments) {
    const family = pickColorFamilyInSegment(segment);
    if (!family) continue;
    const lowered = segment.toLowerCase();
    const matchedSlots = Object.entries(SLOT_KEYWORDS)
      .filter(([, keywords]) => keywords.some((kw) => lowered.includes(String(kw).toLowerCase())))
      .map(([slot]) => slot);
    if (matchedSlots.length === 0) continue;
    for (const slot of matchedSlots) {
      if (!intent[slot]) intent[slot] = family;
    }
  }

  const loweredPrompt = prompt.toLowerCase();
  if (/寒冰|冰蓝|冰霜|霜蓝|ice|icy|frost|glacier/.test(loweredPrompt)) {
    intent.weapons = "ice_blue";
  }
  if (/红.{0,4}(头发|短发|长发|发色)|(?:头发|短发|长发|发色).{0,4}红/.test(loweredPrompt)) {
    intent.hair = "red";
  }
  if (/黑.{0,6}(轻甲|重甲|护甲|盔甲|armor|armour)|(?:轻甲|重甲|护甲|盔甲|armor|armour).{0,6}黑/.test(loweredPrompt)) {
    intent.armor = "black";
  }
  if (/粉.{0,6}(帽|帽子|鸭舌帽|hat|cap)|(?:帽|帽子|鸭舌帽|hat|cap).{0,6}粉/.test(loweredPrompt)) {
    intent.hat = "pink";
  }
  if (/(blond|blonde|gold).{0,12}(hair)|hair.{0,12}(blond|blonde|gold)/.test(loweredPrompt)) {
    intent.hair = "gold";
  }
  if (
    /(navy|blue).{0,20}(skirt|dress|uniform|blouse|kimono)/.test(loweredPrompt) ||
    /(skirt|dress|uniform|blouse|kimono).{0,20}(navy|blue)/.test(loweredPrompt)
  ) {
    intent.armor = "navy";
    if (!intent.legs) intent.legs = "navy";
    if (!intent.torso) intent.torso = "navy";
  }
  if (
    /(red|crimson|scarlet|ruby).{0,20}(shoe|shoes|sneaker|boot|boots|sandals|slipper)/.test(loweredPrompt) ||
    /(shoe|shoes|sneaker|boot|boots|sandals|slipper).{0,20}(red|crimson|scarlet|ruby)/.test(loweredPrompt)
  ) {
    intent.feet = "red";
  }

  return intent;
}

function resolveColorSlot(category, typeName) {
  const normalizedCategory = String(category || "").toLowerCase();
  const normalizedType = String(typeName || "").toLowerCase();
  if (normalizedCategory === "hair" || normalizedType === "hair" || normalizedType === "beard" || normalizedType === "mustache") return "hair";
  if (normalizedCategory === "armor" || normalizedType === "armour" || normalizedType === "armor") return "armor";
  if (normalizedCategory === "legs" || normalizedType === "legs") return "legs";
  if (normalizedCategory === "feet" || normalizedType === "shoes" || normalizedType === "feet") return "feet";
  if (normalizedCategory === "torso" || normalizedType === "dress" || normalizedType === "clothes" || normalizedType === "jacket") return "torso";
  if (normalizedCategory === "weapons" || normalizedType === "weapon" || normalizedType === "shield") return "weapons";
  if (normalizedCategory === "hat" || normalizedType.includes("hat") || normalizedType.includes("headcover") || normalizedType === "headwear") return "hat";
  if (normalizedCategory === "body" || normalizedType === "body" || normalizedType === "head" || normalizedType === "expression") return "body";
  return normalizedCategory || normalizedType || "global";
}

function pickPreferredToken(availableTokens, familyName) {
  if (!familyName || !availableTokens.length) return null;
  const family = COLOR_FAMILIES[familyName];
  if (!family) return null;
  const normalizedAvailable = new Map(availableTokens.map((token) => [canonicalColorToken(token), token]));
  for (const pref of family.tokenPreferences) {
    const direct = normalizedAvailable.get(canonicalColorToken(pref));
    if (direct) return direct;
  }
  return null;
}

function pickBodyPath(layer, bodyType) {
  if (layer[bodyType]) return layer[bodyType];
  for (const key of BODY_KEYS) {
    if (layer[key]) return layer[key];
  }
  return null;
}

function normalizeNameForHash(name) {
  return String(name || "").replaceAll(" ", "_");
}

function getSelectedItemIdForTemplateVariable(variableName, selectedLayers) {
  if (selectedLayers?.[variableName]) return selectedLayers[variableName];
  const entries = Object.entries(selectedLayers || {});
  const direct = entries.find(([, itemId]) => {
    const meta = window.itemMetadata?.[itemId];
    return meta?.type_name === variableName;
  });
  return direct?.[1] || null;
}

function resolveTemplateValue(variableName, meta, selectedLayers) {
  const replaceMap = meta?.replace_in_path?.[variableName];
  if (!replaceMap || typeof replaceMap !== "object") return null;

  const selectedItemId = getSelectedItemIdForTemplateVariable(variableName, selectedLayers);
  if (!selectedItemId) return null;

  const selectedMeta = window.itemMetadata?.[selectedItemId];
  if (!selectedMeta) return null;

  const selectedEntry = Object.entries(selectedLayers || {}).find(([, itemId]) => itemId === selectedItemId);
  const selectedCategory = selectedEntry?.[0] || variableName;
  const selectedToken = pickAssetToken(selectedMeta, selectedItemId, {
    category: selectedCategory,
    colorIntent: state.colorIntent,
  });
  const selectedName = normalizeNameForHash(selectedMeta.name);

  const candidateKeys = [];
  if (selectedName && selectedToken) candidateKeys.push(`${selectedName}_${selectedToken}`);
  if (selectedName) candidateKeys.push(selectedName);
  if (selectedToken) candidateKeys.push(selectedToken);

  for (const key of candidateKeys) {
    if (Object.prototype.hasOwnProperty.call(replaceMap, key)) return replaceMap[key];
    const found = Object.entries(replaceMap).find(([mapKey]) => String(mapKey).toLowerCase() === String(key).toLowerCase());
    if (found) return found[1];
  }
  return null;
}

function resolvePathTemplates(basePath, meta, selectedLayers) {
  const original = String(basePath || "");
  return original.replace(/\$\{([^}]+)\}/g, (full, variableName) => {
    const resolved = resolveTemplateValue(variableName, meta, selectedLayers);
    return resolved ? String(resolved) : full;
  });
}

function pickAssetToken(meta, itemId, { category = null, colorIntent = null } = {}) {
  const variants = Array.isArray(meta.variants) ? meta.variants : [];
  const recolorVariants = Array.isArray(meta.recolors?.[0]?.variants) ? meta.recolors[0].variants : [];
  const availableTokens = variants.length > 0 ? variants : recolorVariants;

  const slot = resolveColorSlot(category, meta.type_name);
  const family = colorIntent?.[slot] || colorIntent?.global || null;
  const preferred = pickPreferredToken(availableTokens, family);
  if (preferred) return preferred;

  if (variants.includes("base")) return "base";
  if (variants.length > 0) return variants[0];
  if (recolorVariants.includes("light")) return "light";
  if (recolorVariants.length > 0) return recolorVariants[0];
  const fallback = String(itemId || "").split("_").pop() || "base";
  return fallback;
}

function appendHashSelection(params, itemId, tokenOverride = null, options = {}) {
  const meta = window.itemMetadata?.[itemId];
  if (!meta?.type_name || !meta?.name) return null;

  const key = meta.type_name;
  const namePart = normalizeNameForHash(meta.name);
  const token = tokenOverride || pickAssetToken(meta, itemId, options);
  params[key] = token ? `${namePart}_${token}` : namePart;
  if (options?.resolvedTokenMap && options?.category) {
    options.resolvedTokenMap[options.category] = token;
  }
  return { key, token };
}

function getCombinedSelectedLayers() {
  return {
    ...state.currentExtendedLayers,
    ...state.currentSelectedLayers,
  };
}

function buildLpcHash(selectedLayers, bodyType) {
  const params = { sex: bodyType || "male" };
  let bodyToken = "light";
  const resolvedTokenMap = {};
  for (const [category, itemId] of Object.entries(selectedLayers || {})) {
    if (!itemId) continue;
    // Skip bookkeeping keys that are not actual LPC categories.
    if (category === "mode_resolved") continue;
    const selection = appendHashSelection(params, itemId, null, {
      category,
      colorIntent: state.colorIntent,
      resolvedTokenMap,
    });
    if (selection?.key === "body" && selection.token) {
      bodyToken = selection.token;
    }
  }

  // If head/expression are not explicitly provided by the backend selection,
  // keep LPC defaults so the character still has a complete face.
  if (!params.head) {
    appendHashSelection(params, "heads_human_male", bodyToken, { category: "head", resolvedTokenMap });
  }
  if (!params.expression) {
    appendHashSelection(params, "face_neutral", bodyToken, { category: "expression", resolvedTokenMap });
  }
  state.resolvedColorTokens = resolvedTokenMap;
  const hash = encodeHashParams(params);
  state.lastResolvedHash = hash;
  return hash;
}

function getLpcPreviewUrl() {
  const backendBase = toBackendOrigin(els.backendUrl.value);
  const hash = buildLpcHash(getCombinedSelectedLayers(), els.bodyType.value);
  const baseUrl = backendBase ? `${backendBase}/generator/index.html` : "/generator/index.html";
  return hash ? `${baseUrl}#${hash}` : baseUrl;
}

function syncLpcPreview(force = false) {
  if (!els.lpcIframe) return;
  const nextUrl = getLpcPreviewUrl();
  if (!force && nextUrl === state.lastLpcUrl) return;
  els.lpcIframe.src = nextUrl;
  state.lastLpcUrl = nextUrl;
}

async function fetchJson(url, options) {
  const resp = await fetch(url, options);
  const text = await resp.text();
  let payload;
  try {
    payload = text ? JSON.parse(text) : {};
  } catch (err) {
    throw new Error(`Invalid JSON: ${text.slice(0, 200)}`);
  }
  if (!resp.ok) {
    throw new Error(payload?.detail || `HTTP ${resp.status}`);
  }
  return payload;
}

function setStatus(text, isError = false) {
  els.statusText.textContent = text;
  els.statusText.style.color = isError ? "#b42318" : "#415168";
}

function renderSummary(data) {
  const tags = [];
  tags.push(`<span class="tag tag-ok">mode: ${data.mode_resolved || "unknown"}</span>`);
  if (data.is_complete) {
    tags.push('<span class="tag tag-ok">已完整命中</span>');
  } else {
    tags.push('<span class="tag tag-warn">存在缺失素材</span>');
  }
  tags.push(`<span class="tag tag-ok">warnings: ${data.warnings_count}</span>`);
  tags.push(`<span class="tag tag-ok">刷新: ${data.manifest_refreshed_at}</span>`);
  els.summaryBox.innerHTML = `
    <div>${tags.join("")}</div>
    <p>${data.character_summary || "（无摘要）"}</p>
    <p class="muted">已命中核心层：${escapeHtml(JSON.stringify(data.selected_layers || {}))}</p>
    <p class="muted">已命中扩展层：${escapeHtml(JSON.stringify(data.extended_layers || {}))}</p>
    <p class="muted">当前 Body Type：${escapeHtml(els.bodyType.value)}</p>
    <p class="muted">当前 LPC Hash：${escapeHtml(state.lastResolvedHash || "无")}</p>
    <p class="muted">颜色规则映射：${Object.keys(state.colorIntent).length ? escapeHtml(JSON.stringify(state.colorIntent)) : "无"}</p>
    <p class="muted">实际命中色票：${Object.keys(state.resolvedColorTokens).length ? escapeHtml(JSON.stringify(state.resolvedColorTokens)) : "无"}</p>
  `;
}

function renderMissingAssets(missingAssets) {
  if (!missingAssets.length) {
    els.missingAssets.innerHTML = '<p class="muted">无缺失资产。</p>';
    return;
  }
  els.missingAssets.innerHTML = missingAssets
    .map(
      (item) => `
      <article class="missing-card">
        <h4>${item.category} / ${item.internal_name}</h4>
        <p><strong>visual_prompt</strong><br />${item.visual_prompt || ""}</p>
        <p><strong>design_notes</strong><br />${item.design_notes || "（无）"}</p>
      </article>
    `,
    )
    .join("");
}

function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderProvenanceRows(rows) {
  els.provenanceBody.innerHTML = rows
    .map((row) => {
      const sourceTag = row.sourceType === "missing" ? "tag-miss" : row.sourceTagClass;
      const sourceLabel = row.sourceType === "missing" ? "需AI生成" : row.sourceLabel;
      const itemCell = row.itemId ? escapeHtml(row.itemId) : "null";
      return `
        <tr>
          <td>${escapeHtml(row.category)}</td>
          <td>${itemCell}</td>
          <td><span class="tag ${sourceTag}">${escapeHtml(sourceLabel)}</span></td>
          <td>${escapeHtml(row.note)}</td>
        </tr>
      `;
    })
    .join("");
}

async function buildProvenance(backendUrl, analyzeResult) {
  const coreLayers = analyzeResult.selected_layers || {};
  const extendedLayers = analyzeResult.extended_layers || {};
  const selectedLayers = { ...extendedLayers, ...coreLayers };
  const orderedCategories = [
    ...CATEGORY_ORDER,
    ...Object.keys(extendedLayers)
      .filter((category) => !CATEGORY_ORDER.includes(category))
      .sort(),
  ];
  const missingByCategory = new Set(
    (analyzeResult.missing_assets || []).map((item) => String(item.category || "").toLowerCase()),
  );

  const selectedIds = orderedCategories
    .map((category) => ({
    category,
    itemId: selectedLayers[category] || null,
    }))
    .filter((item) => item.itemId);

  const lookups = await Promise.all(
    selectedIds.map(async (entry) => {
      try {
        const data = await fetchJson(`${backendUrl}/assets/lookup/${encodeURIComponent(entry.itemId)}`);
        return { ...entry, lookup: data };
      } catch (err) {
        return { ...entry, lookupError: String(err) };
      }
    }),
  );

  const lookupMap = new Map(lookups.map((it) => [it.category, it]));
  const rows = [];

  for (const category of orderedCategories) {
    const itemId = selectedLayers[category] || null;
    if (category === "torso" && itemId && selectedLayers.armor && selectedLayers.armor === itemId) {
      continue;
    }
    if (!itemId) {
      if (!CATEGORY_ORDER.includes(category)) {
        continue;
      }
      rows.push({
        category,
        itemId: null,
        sourceType: "missing",
        sourceLabel: "需AI生成",
        sourceTagClass: "tag-miss",
        note: missingByCategory.has(category) ? "该层在 manifest 中无可用命中" : "该层未选择",
      });
      continue;
    }

    const row = lookupMap.get(category);
    if (!row || row.lookupError) {
      rows.push({
        category,
        itemId,
        sourceType: "existing",
        sourceLabel: "已命中（来源未知）",
        sourceTagClass: "tag-warn",
        note: row?.lookupError || "lookup 失败",
      });
      continue;
    }

    const isCustom = Boolean(row.lookup?.is_custom);
    rows.push({
      category,
      itemId,
      sourceType: "existing",
      sourceLabel: isCustom ? "本地自定义/可能AI生成" : "LPC内置库",
      sourceTagClass: isCustom ? "tag-warn" : "tag-ok",
      note: row.lookup?.definition_file || "",
    });
  }
  return rows;
}

async function applyAnalyzeResult(backendUrl, analyzeResult) {
  state.latestAnalyze = analyzeResult;
  state.currentSelectedLayers = {
    body: null,
    hair: null,
    armor: null,
    weapons: null,
    ...(analyzeResult.selected_layers || {}),
  };
  state.currentExtendedLayers = { ...(analyzeResult.extended_layers || {}) };
  // Refresh resolved color tokens before rendering textual summary.
  buildLpcHash(getCombinedSelectedLayers(), els.bodyType.value);
  renderSummary(analyzeResult);
  renderMissingAssets(analyzeResult.missing_assets || []);
  const rows = await buildProvenance(backendUrl, analyzeResult);
  renderProvenanceRows(rows);
  syncLpcPreview();
}

async function runAnalyze() {
  const backendUrl = normalizeBaseUrl(els.backendUrl.value);
  const prompt = els.promptInput.value.trim();
  if (!backendUrl || !prompt) {
    setStatus("请先填写 Backend URL 和 Prompt。", true);
    return;
  }
  setStatus("分析中...");
  state.colorIntent = extractColorIntent(prompt);
  const inferredBodyType = autoSyncBodyTypeByPrompt(prompt);

  try {
    const analyzeResult = await fetchJson(`${backendUrl}/ai/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, gen_mode: getGenModeEnabled() }),
    });
    await applyAnalyzeResult(backendUrl, analyzeResult);
    if (inferredBodyType) {
      setStatus(`分析完成。已按提示词自动切换体型为 ${inferredBodyType}。`, false);
    } else {
      setStatus("分析完成。", false);
    }
  } catch (err) {
    setStatus(`分析失败：${String(err)}`, true);
  }
}

async function runExecute() {
  const backendUrl = normalizeBaseUrl(els.backendUrl.value);
  const prompt = els.promptInput.value.trim();
  if (!backendUrl || !prompt) {
    setStatus("请先填写 Backend URL 和 Prompt。", true);
    return;
  }
  if (!getGenModeEnabled()) {
    setStatus("GEN 为 OFF，无法执行生图链路。", true);
    return;
  }

  setStatus("执行中（Analyze -> Generate -> Register）...");
  state.colorIntent = extractColorIntent(prompt);
  const inferredBodyType = autoSyncBodyTypeByPrompt(prompt);
  els.executeResult.textContent = "执行中...";

  try {
    const executeResult = await fetchJson(`${backendUrl}/ai/execute`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt,
        gen_mode: true,
        auto_register: true,
        max_generation_tasks: Math.max(1, Number(els.maxTasks.value) || 2),
      }),
    });

    els.executeResult.textContent = JSON.stringify(executeResult, null, 2);
    const analyzeResult = executeResult.analysis_after || executeResult.analysis_before;
    if (analyzeResult) {
      await applyAnalyzeResult(backendUrl, analyzeResult);
    }

    if (executeResult.overall_status === "failed") {
      setStatus("执行完成：全部任务失败。请查看 Execute 结果区错误详情。", true);
    } else if (executeResult.overall_status === "partial_success") {
      setStatus(
        inferredBodyType
          ? `执行完成：部分成功，体型已自动切换为 ${inferredBodyType}。`
          : "执行完成：部分成功。请查看每条 generated_assets 状态。",
        false,
      );
    } else {
      setStatus(
        inferredBodyType
          ? `执行完成：全部成功，体型已自动切换为 ${inferredBodyType}。`
          : "执行完成：全部成功。",
        false,
      );
    }
  } catch (err) {
    els.executeResult.textContent = String(err);
    setStatus(`执行失败：${String(err)}`, true);
  }
}

if (els.syncLpcBtn) {
  els.syncLpcBtn.addEventListener("click", () => {
    syncLpcPreview(true);
    setStatus("已同步当前命中层到 LPC 原生预览。");
  });
}

if (els.openLpcBtn) {
  els.openLpcBtn.addEventListener("click", () => {
    const url = getLpcPreviewUrl();
    window.open(url, "_blank", "noopener,noreferrer");
  });
}

els.analyzeBtn.addEventListener("click", runAnalyze);
els.executeBtn.addEventListener("click", runExecute);
els.bodyType.addEventListener("change", () => {
  buildLpcHash(getCombinedSelectedLayers(), els.bodyType.value);
  if (state.latestAnalyze) {
    renderSummary(state.latestAnalyze);
  }
  syncLpcPreview(true);
});
els.genMode.addEventListener("change", updateGenUi);
updateGenUi();
syncLpcPreview(true);
