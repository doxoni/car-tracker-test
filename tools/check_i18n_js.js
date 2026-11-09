// -*- coding: utf-8 -*-
// Проверка клиентского движка перевода без браузера.
// Запуск: node tools/check_i18n_js.js

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..");

// Минимальный DOM: движку нужен document.body и createTreeWalker.
function makeElement(tag) {
  return {
    nodeType: 1,
    tagName: tag.toUpperCase(),
    nodeValue: "",
    attributes: {},
    children: [],
    getAttribute(name) {
      return name in this.attributes ? this.attributes[name] : null;
    },
    setAttribute(name, value) {
      this.attributes[name] = value;
    },
    removeAttribute(name) {
      delete this.attributes[name];
    },
  };
}

const body = makeElement("body");
const document = {
  readyState: "complete",
  body: body,
  title: "Car Tracker",
  documentElement: makeElement("html"),
  // Узлы, которые обходит TreeWalker: по одному за вызов nextNode.
  walkNodes: [],
  // Фильтр вызывается для каждого узла, как в браузере.
  walkFilter: null,
  createTreeWalker(root, whatToShow, filter) {
    const nodes = document.walkNodes;
    let index = 0;
    document.walkFilter = filter;
    return {
      nextNode() {
        while (index < nodes.length) {
          const node = nodes[index++];
          const verdict = document.walkFilter ? document.walkFilter(node) : 1;
          // 2 - FILTER_REJECT: узел пропускаем целиком.
          if (verdict === 2) continue;
          return node;
        }
        return null;
      },
    };
  },
  getElementById: () => null,
  addEventListener: () => {},
};

const sandbox = {
  window: {
    CT_DICT: {},
    CT_FRAG: [],
    location: { search: "", reload: () => {} },
    localStorage: {
      getItem: () => "",
      setItem: () => {},
    },
    fetch: () => Promise.resolve({ json: () => Promise.resolve({}) }),
  },
  document: document,
  localStorage: {
    getItem: () => "",
    setItem: () => {},
  },
  fetch: () => Promise.resolve({ json: () => Promise.resolve({}) }),
  URLSearchParams: URLSearchParams,
  console: console,
};
sandbox.window.document = document;
sandbox.window.window = sandbox.window;

// Загружаем словарь и движок.
const dictSource = fs.readFileSync(
  path.join(ROOT, "app", "static", "i18n_dict.js"),
  "utf8"
);
const engineSource = fs.readFileSync(
  path.join(ROOT, "app", "static", "i18n.js"),
  "utf8"
);

vm.createContext(sandbox);
vm.runInContext(dictSource, sandbox);
vm.runInContext(engineSource, sandbox);

const tr = sandbox.window.CT_I18N.t;

const checks = [
  ["Пробег:", "Пробіг:"],
  ["Заправки:", "Заправки:"],
  ["Не удалось загрузить дашборд", "Не вдалося завантажити дашборд"],
  ["Загрузка…", "Завантаження…"],
];

let failed = 0;
for (const [source, expected] of checks) {
  const got = tr(source, "uk");
  if (got !== expected) {
    console.log("НЕ СОВПАЛО:", JSON.stringify(source), "->", JSON.stringify(got));
    failed++;
  }
}

// Русский текст при русском языке не меняется.
if (tr("Пробег:", "ru") !== "Пробег:") {
  console.log("РУССКИЙ ИСПОРЧЕН:", JSON.stringify(tr("Пробег:", "ru")));
  failed++;
}

// Куски строк переводятся внутри длинной фразы.
// "Заправок" в украинском пишется так же, переводится "раз(ов)".
const long = tr("Заправок: 12 раз(ов), 400 л", "uk");
if (long.indexOf("раз(ів)") < 0 || long.indexOf("12") < 0) {
  console.log("КУСОК СТРОКИ НЕ ПЕРЕВЕДЁН:", JSON.stringify(long));
  failed++;
}

// Проверяем куски строк.
const frag = sandbox.window.CT_FRAG;
console.log("Кусков строк:", frag.length);
if (frag.indexOf("Заправок:") < 0) {
  console.log("НЕТ КУСКА 'Заправок:'");
  failed++;
}

// ---------- обход дерева ----------
// Движок должен перевести все узлы дерева, а не только первый.
function makeText(value) {
  return { nodeType: 3, nodeValue: value };
}

const nodes = [makeText("Период"), makeText("Мои автомобили"), makeText("Отчёт")];
document.walkNodes = nodes;
// Язык украинский - иначе движок ничего не переводит.
sandbox.window.CT_I18N.setLang("uk");
sandbox.window.CT_I18N.translateTree(body);

const expected = ["Період", "Мої автомобілі", "Звіт"];
for (let i = 0; i < nodes.length; i++) {
  if (nodes[i].nodeValue !== expected[i]) {
    console.log(
      "УЗЕЛ НЕ ПЕРЕВЕДЁН:",
      JSON.stringify(nodes[i].nodeValue),
      "ожидалось",
      JSON.stringify(expected[i])
    );
    failed++;
  }
}

console.log(failed ? `ПРОВАЛЕНО: ${failed}` : "ВСЁ ОК");
process.exit(failed ? 1 : 0);
