(function (window) {
  if (!window.Asc || !window.Asc.plugin) return;

  var STORAGE_KEY = 'onlyoffice-search-bridge-message';
  var CHANNEL_NAME = 'onlyoffice-search-bridge';
  var RESULT_SOURCE = 'onlyoffice-search-bridge';
  var DEBUG = false;
  var SEARCH_TIMEOUT_MS = 900;
  var POLL_INTERVAL_MS = 500;
  var API_RETRY_INTERVAL_MS = 250;
  var lastNonce = null;
  var pollTimer = null;
  var retryTimer = null;
  var pendingMessage = null;

  function normalizeText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function sourceLines(text) {
    return String(text || '')
      .split(/\r\n|\r|\n/)
      .map(normalizeText)
      .filter(Boolean);
  }

  function buildSearchCandidates(text) {
    var cleanText = normalizeText(text);
    if (!cleanText) return [];

    var candidates = [cleanText];
    var clauses = cleanText.split(/[。；;，,：:、]/);
    for (var i = 0; i < clauses.length; i += 1) candidates.push(clauses[i]);
    if (cleanText.length > 24) {
      candidates.push(cleanText.slice(0, 32));
      candidates.push(cleanText.slice(0, Math.max(12, Math.ceil(cleanText.length * 0.45))));
    }

    var unique = [];
    for (var j = 0; j < candidates.length; j += 1) {
      var item = normalizeText(candidates[j]);
      if (item.length < 8) continue;
      if (unique.indexOf(item) === -1) unique.push(item);
      if (unique.length >= 4) break;
    }
    return unique;
  }

  function postResult(message, found, candidate, detail) {
    try {
      if (!window.top || window.top === window) return;
      window.top.postMessage({
        source: RESULT_SOURCE,
        type: 'search-result',
        nonce: message && message.nonce,
        found: Boolean(found),
        candidate: candidate || '',
        detail: detail || null,
      }, '*');
    } catch (e) {}
  }

  function postDebug(stage, detail) {
    if (!DEBUG) return;
    try {
      if (!window.top || window.top === window) return;
      var safeDetail = '';
      try {
        safeDetail = typeof detail === 'string' ? detail : JSON.stringify(detail || '');
      } catch (e) {
        safeDetail = String(detail || '');
      }
      window.top.postMessage({
        source: RESULT_SOURCE,
        type: 'search-debug',
        stage: stage,
        detail: safeDetail,
      }, '*');
    } catch (e) {}
  }

  function apiReady() {
    return Boolean(window.Asc && window.Asc.plugin);
  }

  function schedulePendingRetry() {
    if (retryTimer) return;
    retryTimer = window.setTimeout(function () {
      retryTimer = null;
      if (pendingMessage) runSearch(pendingMessage, true);
    }, API_RETRY_INTERVAL_MS);
  }

  function runParagraphSearch(text, callback) {
    if (typeof window.Asc.plugin.callCommand !== 'function') {
      callback({ ok: false, reason: 'callCommand-unavailable' });
      return;
    }

    window.Asc.scope.searchText = text;
    try {
      window.Asc.plugin.callCommand(function () {
        function normalizeLine(value) {
          return String(value || '').replace(/\s+/g, ' ').trim();
        }

        function getSourceLines(value) {
          return String(value || '')
            .split(/\r\n|\r|\n/)
            .map(normalizeLine)
            .filter(Boolean);
        }

        function containsLinesInOrder(textValue, linesValue) {
          var cursor = 0;
          for (var i = 0; i < linesValue.length; i += 1) {
            var index = textValue.indexOf(linesValue[i], cursor);
            if (index === -1) return false;
            cursor = index + linesValue[i].length;
          }
          return true;
        }

        function selectParagraph(paragraph, firstLine) {
          if (paragraph && paragraph.GetRange && paragraph.GetText) {
            var paragraphText = String(paragraph.GetText() || '');
            var start = paragraphText.indexOf(firstLine);
            if (start < 0) start = 0;
            var end = Math.min(paragraphText.length, start + firstLine.length);
            var range = paragraph.GetRange(start, end);
            if (range && range.Select) {
              range.Select();
              return 'range.Select';
            }
          }
          if (paragraph && paragraph.Select) {
            paragraph.Select();
            return 'paragraph.Select';
          }
          return 'no-select-method';
        }

        var lines = getSourceLines(window.Asc.scope.searchText);
        var result = { ok: false, mode: lines.length > 1 ? 'multiline' : 'single-line', lineCount: lines.length, reason: 'not-run' };
        if (!lines.length) {
          result.reason = 'empty-source';
          return result;
        }
        if (typeof Api === 'undefined' || !Api.GetDocument) {
          result.reason = 'Api.GetDocument-unavailable';
          return result;
        }
        var document = Api.GetDocument();
        if (!document || !document.GetAllParagraphs) {
          result.reason = 'GetAllParagraphs-unavailable';
          return result;
        }
        var paragraphs = document.GetAllParagraphs();
        var entries = [];
        for (var i = 0; i < paragraphs.length; i += 1) {
          var paragraph = paragraphs[i];
          var paragraphText = paragraph && paragraph.GetText ? normalizeLine(paragraph.GetText()) : '';
          if (paragraphText) entries.push({ paragraph: paragraph, text: paragraphText });
        }
        result.paragraphCount = paragraphs.length;
        result.nonEmptyParagraphCount = entries.length;
        for (var start = 0; start < entries.length; start += 1) {
          if (entries[start].text.indexOf(lines[0]) === -1) continue;
          var windowText = '';
          var maxEnd = Math.min(entries.length, start + lines.length + 8);
          for (var end = start; end < maxEnd; end += 1) {
            windowText += (windowText ? '\n' : '') + entries[end].text;
            if (containsLinesInOrder(windowText, lines)) {
              result.ok = true;
              result.reason = 'matched';
              result.startIndex = start;
              result.endIndex = end;
              result.selectMethod = selectParagraph(entries[start].paragraph, lines[0]);
              return result;
            }
          }
        }
        result.reason = 'not-found';
        result.firstLine = lines[0];
        return result;
      }, false, true, function (result) {
        callback(result || { ok: false, reason: 'no-return-value' });
      });
    } catch (error) {
      callback({ ok: false, reason: 'callCommand-error', message: error && error.message ? error.message : String(error) });
    }
  }

  function searchCandidate(candidate, isForward, callback) {
    if (typeof window.Asc.plugin.executeMethod !== 'function') {
      callback(false);
      return;
    }
    var settled = false;
    var timer = window.setTimeout(function () {
      if (settled) return;
      settled = true;
      postDebug('search-timeout', { candidate: candidate, isForward: Boolean(isForward) });
      callback(false);
    }, SEARCH_TIMEOUT_MS);

    try {
      window.Asc.plugin.executeMethod(
        'SearchNext',
        [
          {
            searchString: candidate,
            matchCase: false,
          },
          Boolean(isForward),
        ],
        function (found) {
          if (settled) return;
          settled = true;
          window.clearTimeout(timer);
          callback(Boolean(found));
        }
      );
    } catch (e) {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      callback(false);
    }
  }

  function searchCandidates(message, candidates, index, paragraphDetail) {
    if (index >= candidates.length) {
      postResult(message, false, '', paragraphDetail);
      return;
    }

    var candidate = candidates[index];
    searchCandidate(candidate, true, function (foundForward) {
      if (foundForward) {
        postResult(message, true, candidate, paragraphDetail);
        return;
      }
      searchCandidate(candidate, false, function (foundBackward) {
        if (foundBackward) {
          postResult(message, true, candidate, paragraphDetail);
          return;
        }
        searchCandidates(message, candidates, index + 1, paragraphDetail);
      });
    });
  }

  function runSearch(message, isRetry) {
    if (!message || message.type !== 'search-basis-text' || !message.text) return;

    if (!apiReady()) {
      pendingMessage = message;
      schedulePendingRetry();
      return;
    }

    if (message.nonce && message.nonce === lastNonce && !isRetry) return;
    lastNonce = message.nonce || String(Date.now());
    pendingMessage = null;

    var candidates = buildSearchCandidates(message.text);
    if (!sourceLines(message.text).length || !candidates.length) {
      postResult(message, false, '', { reason: 'empty-source' });
      return;
    }

    runParagraphSearch(message.text, function (paragraphResult) {
      postDebug('paragraph-result', paragraphResult);
      if (paragraphResult && paragraphResult.ok) {
        postResult(message, true, candidates[0], paragraphResult);
        return;
      }
      searchCandidates(message, candidates, 0, paragraphResult);
    });
  }

  function runStoredSearch() {
    try {
      var raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) runSearch(JSON.parse(raw));
    } catch (e) {}
  }

  function startPolling() {
    if (pollTimer) return;
    pollTimer = window.setInterval(runStoredSearch, POLL_INTERVAL_MS);
  }

  window.Asc.plugin.init = function () {
    window.setTimeout(runStoredSearch, API_RETRY_INTERVAL_MS);
    startPolling();
  };

  window.addEventListener('storage', function (event) {
    if (event.key !== STORAGE_KEY || !event.newValue) return;
    try {
      runSearch(JSON.parse(event.newValue));
    } catch (e) {}
  });

  if ('BroadcastChannel' in window) {
    var channel = new BroadcastChannel(CHANNEL_NAME);
    channel.onmessage = function (event) {
      runSearch(event.data);
    };
  }
})(window);
