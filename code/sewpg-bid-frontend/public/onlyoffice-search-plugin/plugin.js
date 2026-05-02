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

  function buildSearchCandidates(text) {
    var cleanText = normalizeText(text);
    if (!cleanText) return [];

    var candidates = [];
    var clauses = cleanText.split(/[。；;，,：:、]/);
    for (var i = 0; i < clauses.length; i += 1) {
      candidates.push(clauses[i]);
    }

    if (cleanText.length > 0) {
      candidates.push(cleanText.slice(0, 24));
      candidates.push(cleanText.slice(0, 32));
    }

    if (cleanText.length > 24) {
      var fallbackLength = Math.max(12, Math.ceil(cleanText.length * 0.45));
      candidates.push(cleanText.slice(0, fallbackLength));
    }

    var unique = [];
    for (var j = 0; j < candidates.length; j += 1) {
      var item = normalizeText(candidates[j]);
      if (item.length < 8) continue;
      if (unique.indexOf(item) === -1) unique.push(item);
      if (unique.length >= 3) break;
    }
    return unique;
  }

  function postResult(message, found, candidate) {
    try {
      if (!window.top || window.top === window) return;
      postDebug('post-result', {
        nonce: message && message.nonce,
        found: Boolean(found),
        candidate: candidate || '',
      });
      window.top.postMessage({
        source: RESULT_SOURCE,
        type: 'search-result',
        nonce: message && message.nonce,
        found: Boolean(found),
        candidate: candidate || '',
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
    return Boolean(
      window.Asc &&
        window.Asc.plugin &&
        typeof window.Asc.plugin.executeMethod === 'function'
    );
  }

  function schedulePendingRetry() {
    if (retryTimer) return;
    retryTimer = window.setTimeout(function () {
      retryTimer = null;
      if (pendingMessage) runSearch(pendingMessage, true);
    }, API_RETRY_INTERVAL_MS);
  }

  function searchCandidate(candidate, isForward, callback) {
    var settled = false;
    var timer = window.setTimeout(function () {
      if (settled) return;
      settled = true;
      postDebug('search-timeout', { candidate: candidate, isForward: Boolean(isForward) });
      callback(false);
    }, SEARCH_TIMEOUT_MS);

    try {
      postDebug('search-start', { candidate: candidate, isForward: Boolean(isForward) });
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
          postDebug('search-callback', { candidate: candidate, isForward: Boolean(isForward), found: Boolean(found) });
          if (settled) return;
          settled = true;
          window.clearTimeout(timer);
          callback(Boolean(found));
        }
      );
      postDebug('search-dispatched', { candidate: candidate, isForward: Boolean(isForward) });
    } catch (e) {
      postDebug('search-error', String(e && (e.message || e) || 'unknown'));
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      callback(false);
    }
  }

  function searchCandidates(message, candidates, index) {
    if (index >= candidates.length) {
      postResult(message, false, '');
      return;
    }

    var candidate = candidates[index];
    searchCandidate(candidate, true, function (foundForward) {
      if (foundForward) {
        postResult(message, true, candidate);
        return;
      }

      searchCandidate(candidate, false, function (foundBackward) {
        if (foundBackward) {
          postResult(message, true, candidate);
          return;
        }

        searchCandidates(message, candidates, index + 1);
      });
    });
  }

  function runSearch(message, isRetry) {
    if (!message || message.type !== 'search-basis-text' || !message.text) return;

    if (!apiReady()) {
      pendingMessage = message;
      postDebug('api-not-ready', { nonce: message.nonce || '' });
      schedulePendingRetry();
      return;
    }

    if (message.nonce && message.nonce === lastNonce && !isRetry) return;
    lastNonce = message.nonce || String(Date.now());
    pendingMessage = null;

    var candidates = buildSearchCandidates(message.text);
    postDebug('runSearch', { nonce: lastNonce, candidates: candidates });
    if (!candidates.length) {
      postResult(message, false, '');
      return;
    }
    searchCandidates(message, candidates, 0);
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
    postDebug('init');
    window.setTimeout(runStoredSearch, API_RETRY_INTERVAL_MS);
    startPolling();
  };

  window.addEventListener('storage', function (event) {
    if (event.key !== STORAGE_KEY || !event.newValue) return;
    try {
      postDebug('storage');
      runSearch(JSON.parse(event.newValue));
    } catch (e) {}
  });

  if ('BroadcastChannel' in window) {
    var channel = new BroadcastChannel(CHANNEL_NAME);
    channel.onmessage = function (event) {
      postDebug('broadcast');
      runSearch(event.data);
    };
  }
})(window);
