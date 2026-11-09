// -*- coding: utf-8 -*-
// Перевод интерфейса Mini App на украинский.
//
// Исходники интерфейса на русском (так требует AGENTS.md), украинский
// появляется только через словарь window.CT_DICT (русский -> украинский).
// Движок переводит видимый текст и подписи атрибутов, следит за новыми
// кусками разметки и помнит выбранный язык.
//
// Запуск: подключается в <head> страницы Mini App:
//   <script src="/static/i18n_dict.js"></script>
//   <script src="/static/i18n.js"></script>

(function () {
  "use strict";

  var DICT = window.CT_DICT || {};

  // Подписи, которые встречаются внутри длинных строк: "Заправок: 12".
  var FRAG = (window.CT_FRAG || []).slice().sort(function (a, b) {
    return b.length - a.length;
  });

  var STORAGE_KEY = "ct_lang";
  var LANGS = ["ru", "uk"];
  var ATTRS = ["placeholder", "title", "aria-label"];
  var WORD_CHARS = /[0-9A-Za-zА-Яа-яЁёІіЇїЄєҐґ]/;
  var WORD_LIKE = /^[0-9A-Za-zА-Яа-яЁёІіЇїЄєҐґ]+(?:[ \t]+[0-9A-Za-zА-Яа-яЁёІіЇїЄєҐґ]+)*$/;

  var state = { lang: "ru" };
  var listeners = [];

  // Что уже перевели: значения, которые сами поставили, второй раз не трогаем.
  var attrState = new WeakMap();
  var textState = new WeakMap();

  function normalize(value) {
    var text = String(value == null ? "" : value).trim().toLowerCase();
    return LANGS.indexOf(text) >= 0 ? text : "";
  }

  // Заменить все вхождения подписи, не задевая похожие слова.
  function replaceAll(source, key, value) {
    if (!key) return source;
    var out = "";
    var pos = 0;
    while (true) {
      var index = source.indexOf(key, pos);
      if (index < 0) {
        out += source.slice(pos);
        break;
      }
      var before = index > 0 ? source.charAt(index - 1) : "";
      var after = source.charAt(index + key.length) || "";
      var fits = true;
      if (WORD_LIKE.test(key)) {
        if (before && WORD_CHARS.test(before)) fits = false;
        if (after && WORD_CHARS.test(after)) fits = false;
      }
      if (!fits) {
        out += source.slice(pos, index + key.length);
        pos = index + key.length;
        continue;
      }
      out += source.slice(pos, index) + value;
      pos = index + key.length;
    }
    return out;
  }

  // Перевод строки: сначала точное совпадение, потом подписи внутри строки.
  // Язык можно указать явно (tr(text, "uk")), иначе берётся выбранный.
  function translateText(text, lang) {
    if (text == null) return text;
    var source = String(text);
    var target = lang ? normalize(lang) : state.lang;
    if (target !== "uk" || !source) return source;

    var lead = source.match(/^\s*/)[0];
    var trail = source.match(/\s*$/)[0];
    var core = source.slice(lead.length, source.length - trail.length);
    if (!core) return source;

    var exact = DICT[core];
    if (exact != null) return lead + exact + trail;

    var result = core;
    for (var i = 0; i < FRAG.length; i++) {
      var key = FRAG[i];
      var value = DICT[key];
      if (value == null || value === key) continue;
      result = replaceAll(result, key, value);
    }
    return result === core ? source : lead + result + trail;
  }

  function translateTextNode(node) {
    if (!node || node.nodeType !== 3) return;
    var current = node.nodeValue;
    var done = textState.get(node);
    if (done === current) return;
    var result = translateText(current);
    if (result === current) return;
    node.nodeValue = result;
    textState.set(node, result);
  }

  function translateAttributes(element) {
    if (!element || element.nodeType !== 1 || !element.getAttribute) return;
    var done = attrState.get(element) || {};
    for (var i = 0; i < ATTRS.length; i++) {
      var name = ATTRS[i];
      var current = element.getAttribute(name);
      if (current == null) continue;
      if (done[name] === current) continue;
      var result = translateText(current);
      if (result === current) continue;
      element.setAttribute(name, result);
      done[name] = result;
    }
    attrState.set(element, done);
  }

  // Обойти поддерево: видимый текст и подписи атрибутов.
  // Скрипты и стили не трогаем - там код, а не текст для человека.
  function translateTree(root) {
    if (!root) return;
    if (root.nodeType === 3) {
      translateTextNode(root);
      return;
    }
    if (root.nodeType !== 1) return;
    translateAttributes(root);
    var walker = document.createTreeWalker(root, 5, function (node) {
      if (node.nodeType === 1) {
        var tag = node.tagName;
        if (tag === "SCRIPT" || tag === "STYLE" || tag === "NOSCRIPT") return 2;
        translateAttributes(node);
        return 3;
      }
      translateTextNode(node);
      return 1;
    });
    // Обходим всё дерево: nextNode возвращает узлы по одному.
    while (walker.nextNode()) {
      /* пусто - перевод делает функция-фильтр */
    }
  }

  function startObserver() {
    if (!window.MutationObserver || !document.body) return;
    var observer = new MutationObserver(function (records) {
      for (var i = 0; i < records.length; i++) {
        var record = records[i];
        if (record.type === "childList") {
          for (var j = 0; j < record.addedNodes.length; j++) {
            translateTree(record.addedNodes[j]);
          }
        } else if (record.type === "attributes") {
          translateAttributes(record.target);
        }
      }
    });
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ATTRS
    });
  }

  // ---------- сохранение языка ----------

  function initData() {
    if (window.Telegram && window.Telegram.WebApp) {
      return window.Telegram.WebApp.initData || "";
    }
    return "";
  }

  function saveLang(lang) {
    try {
      localStorage.setItem(STORAGE_KEY, lang);
    } catch (error) {
      // приватный режим браузера - просто не сохраняем
    }
    var headers = { "Content-Type": "application/json" };
    var data = initData();
    if (data) headers["X-Telegram-Init-Data"] = data;
    return fetch("/api/language", {
      method: "POST",
      headers: headers,
      body: JSON.stringify({ lang: lang })
    }).catch(function () { return null; });
  }

  // Переключить язык: запомнить и перезагрузить страницу.
  // После перезагрузки весь интерфейс снова на русском в исходниках,
  // и движок переводит его заново - так ничего не теряется и не дублируется.
  function setLang(lang) {
    var next = normalize(lang) || "ru";
    state.lang = next;
    document.documentElement.setAttribute("lang", next);
    for (var i = 0; i < listeners.length; i++) {
      try { listeners[i](next); } catch (error) { /* слушатель не сорвал переключение */ }
    }
    return saveLang(next).then(function () {
      window.location.reload();
    });
  }

  // ---------- выбор языка ----------

  var picker = null;

  function closePicker() {
    if (!picker) return;
    if (picker.parentNode) picker.parentNode.removeChild(picker);
    picker = null;
  }

  function showPicker() {
    if (picker) return;
    var overlay = document.createElement("div");
    overlay.className = "ct-lang-overlay";
    overlay.style.cssText = [
      "position:fixed", "inset:0", "z-index:99999",
      "background:rgba(0,0,0,.65)",
      "display:flex", "align-items:center", "justify-content:center", "padding:20px"
    ].join(";");

    var box = document.createElement("div");
    box.style.cssText = [
      "background:var(--card,#fff)", "color:var(--text,#111)",
      "border-radius:16px", "padding:20px", "max-width:320px", "width:100%",
      "display:flex", "flex-direction:column", "gap:10px"
    ].join(";");

    var title = document.createElement("div");
    title.textContent = "Выберите язык / Виберіть мову";
    title.style.cssText = "font-size:16px;font-weight:600;text-align:center";

    var ru = document.createElement("button");
    ru.type = "button";
    ru.textContent = "🇷🇺 Русский";
    ru.style.cssText = buttonStyle();

    var uk = document.createElement("button");
    uk.type = "button";
    uk.textContent = "🇺🇦 Українська";
    uk.style.cssText = buttonStyle();

    ru.addEventListener("click", function () { closePicker(); setLang("ru"); });
    uk.addEventListener("click", function () { closePicker(); setLang("uk"); });

    box.appendChild(title);
    box.appendChild(ru);
    box.appendChild(uk);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    picker = overlay;
  }

  function buttonStyle() {
    return [
      "min-height:48px", "border-radius:12px", "border:1px solid var(--line,#ddd)",
      "background:var(--btn,#f2f2f7)", "color:var(--text,#111)",
      "font-size:16px", "cursor:pointer"
    ].join(";");
  }

  // Кнопка смены языка: на странице для этого есть элемент #btn-lang.
  function bindLangButton() {
    var button = document.getElementById("btn-lang");
    if (!button) return;
    button.addEventListener("click", function () {
      showPicker();
    });
    updateLangButton();
  }

  function updateLangButton() {
    var button = document.getElementById("btn-lang");
    if (!button) return;
    button.textContent = state.lang === "uk" ? "🇺🇦 Українська" : "🇷🇺 Русский";
  }

  // ---------- запуск ----------

  function applyLang(lang) {
    state.lang = normalize(lang) || "ru";
    document.documentElement.setAttribute("lang", state.lang);
    if (state.lang === "uk") {
      translateTree(document.body);
      if (document.title) {
        var title = translateText(document.title);
        if (title !== document.title) document.title = title;
      }
    }
    updateLangButton();
  }

  function storedLang() {
    var value = "";
    try {
      value = localStorage.getItem(STORAGE_KEY) || "";
    } catch (error) {
      value = "";
    }
    return normalize(value);
  }

  function paramLang() {
    try {
      return normalize(new URLSearchParams(window.location.search).get("lang"));
    } catch (error) {
      return "";
    }
  }

  function boot() {
    bindLangButton();

    var fromParam = paramLang();
    var fromStorage = storedLang();

    if (fromParam) {
      // Ссылка из бота: язык из адреса важнее всего, запоминаем его.
      applyLang(fromParam);
      startObserver();
      saveLang(fromParam);
      return;
    }

    if (fromStorage) {
      applyLang(fromStorage);
      startObserver();
      return;
    }

    // Язык ещё не выбран: спрашиваем сервер, он знает выбор из бота.
    var headers = {};
    var data = initData();
    if (data) headers["X-Telegram-Init-Data"] = data;
    fetch("/api/language", { headers: headers })
      .then(function (response) { return response.json(); })
      .then(function (payload) {
        var lang = normalize(payload && payload.lang);
        if (lang) {
          applyLang(lang);
          startObserver();
          return;
        }
        showPicker();
      })
      .catch(function () {
        showPicker();
      });
  }

  window.tr = translateText;
  window.CT_I18N = {
    get lang() { return state.lang; },
    t: translateText,
    setLang: setLang,
    showPicker: showPicker,
    translateTree: translateTree,
    onChange: function (callback) { listeners.push(callback); }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
