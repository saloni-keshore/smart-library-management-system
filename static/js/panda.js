document.addEventListener("DOMContentLoaded", function () {

    var widget = document.getElementById("pandaWidget");
    if (!widget) return;

    var csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;

    var toggleBtn = document.getElementById("pandaToggleBtn");
    var panel = document.getElementById("pandaPanel");
    var badge = document.getElementById("pandaBadge");
    var closeBtn = document.getElementById("pandaCloseBtn");
    var minimizeBtn = document.getElementById("pandaMinimizeBtn");
    var newChatBtn = document.getElementById("pandaNewChatBtn");
    var historyBtn = document.getElementById("pandaHistoryBtn");
    var historyCloseBtn = document.getElementById("pandaHistoryCloseBtn");
    var historyPanel = document.getElementById("pandaHistoryPanel");
    var historyList = document.getElementById("pandaHistoryList");
    var welcome = document.getElementById("pandaWelcome");
    var insightsEl = document.getElementById("pandaInsights");
    var suggestionsEl = document.getElementById("pandaSuggestions");
    var messagesEl = document.getElementById("pandaMessages");
    var body = document.getElementById("pandaBody");
    var form = document.getElementById("pandaInputForm");
    var input = document.getElementById("pandaInput");
    var sendBtn = document.getElementById("pandaSendBtn");

    var insightsUrl = widget.dataset.insightsUrl;
    var questionsUrl = widget.dataset.questionsUrl;
    var conversationsUrl = widget.dataset.conversationsUrl;

    var currentConversationId = null;
    var insightsLoaded = false;

    // Shown only when the response actually carries session/CSRF-lapse
    // evidence: a 401 (routes.py's own _require_admin() check), or a 400
    // with an unparseable (HTML) body - specifically app.py's app-wide CSRF
    // guard in enforce_request_security, which is the one place a 400
    // response is *not* JSON, aborting before a Panda route even runs
    // because the session/CSRF token from the page load no longer matches.
    // Distinct from CHAT_UNAVAILABLE_RESPONSE's message (panda/routes.py),
    // a real, different condition (chat tables not migrated yet).
    var SESSION_EXPIRED_MESSAGE = "Your session has expired. Please refresh the page and log in again.";

    // Shown for a non-JSON/unparseable response that ISN'T the CSRF-guard's
    // 400 above - a genuine backend or network failure (e.g. an unhandled
    // 500 from a transient Supabase hiccup - see
    // database.panda_queries.ChatStorageTemporarilyUnavailable, added
    // 2026-08-24) rather than anything to do with this admin's session.
    // Telling the admin to "log in again" for a one-off backend blip that
    // has nothing to do with their login would be actively misleading -
    // this is the honest "it's not you, try again" alternative.
    var SERVICE_UNAVAILABLE_MESSAGE = "Panda couldn't reach the server just now. Please try again in a moment.";

    function escapeHtml(value) {
        var div = document.createElement("div");
        div.textContent = value === null || value === undefined ? "" : String(value);
        return div.innerHTML;
    }

    function jsonFetch(url, options) {
        options = options || {};
        options.headers = Object.assign(
            { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
            options.headers || {}
        );
        return fetch(url, options).then(function (response) {
            return response.json().then(function (data) {
                return { ok: response.ok, status: response.status, data: data };
            }).catch(function () {
                // Non-JSON body (e.g. the CSRF-guard's HTML error page from
                // a lapsed session, or a raw 500 HTML error page from an
                // unrelated backend failure) - surface it as a normal
                // failed result instead of rejecting the whole promise, so
                // callers can still inspect the status code and tell the
                // two apart (see isSessionLapse()/isBackendFailure() below).
                return { ok: false, status: response.status, data: {}, parseError: true };
            });
        });
    }

    // Session/CSRF-lapse evidence only: a real 401, or the CSRF guard's
    // specific 400+non-JSON combination. A parse failure on any *other*
    // status code (500, 502, 503...) is not session evidence - see
    // isBackendFailure() below, which is what those actually mean.
    function isSessionLapse(result) {
        return result.status === 401 || (result.status === 400 && result.parseError === true);
    }

    // A non-JSON response that isn't the session-lapse case above - a
    // genuine backend/network failure (unhandled exception, transient
    // Supabase blip, proxy timeout...), not anything about this admin's
    // login state.
    function isBackendFailure(result) {
        return result.parseError === true && !isSessionLapse(result);
    }

    // ------------------------------------------------------------------
    // Open / close / minimize
    // ------------------------------------------------------------------

    function openPanel() {
        panel.hidden = false;
        requestAnimationFrame(function () {
            panel.classList.add("panda-panel-open");
        });
        toggleBtn.setAttribute("aria-expanded", "true");
        if (!insightsLoaded) {
            loadInsights();
            loadSuggestions();
            insightsLoaded = true;
        }
    }

    function closePanel() {
        panel.classList.remove("panda-panel-open");
        toggleBtn.setAttribute("aria-expanded", "false");
        setTimeout(function () { panel.hidden = true; }, 180);
    }

    toggleBtn.addEventListener("click", function () {
        if (panel.hidden) {
            openPanel();
        } else {
            closePanel();
        }
    });

    closeBtn.addEventListener("click", closePanel);
    minimizeBtn.addEventListener("click", closePanel);

    // ------------------------------------------------------------------
    // Today's AI Insights
    // ------------------------------------------------------------------

    var SEVERITY_ICON_COLOR = { critical: "bi-exclamation-octagon-fill", warning: "bi-exclamation-triangle-fill", info: "bi-info-circle-fill" };

    function loadInsights() {
        jsonFetch(insightsUrl, { method: "GET", headers: {} }).then(function (result) {
            if (!result.ok) {
                insightsEl.innerHTML = '<div class="panda-insights-empty">Couldn\'t load insights right now.</div>';
                return;
            }
            renderInsights(result.data.insights || []);
        }).catch(function () {
            insightsEl.innerHTML = '<div class="panda-insights-empty">Couldn\'t load insights right now.</div>';
        });
    }

    function renderInsights(insights) {
        if (insights.length === 0) {
            insightsEl.innerHTML = '<div class="panda-insights-empty">You\'re all caught up - no alerts right now.</div>';
            badge.hidden = true;
            return;
        }

        insightsEl.innerHTML = insights.map(function (item) {
            var icon = SEVERITY_ICON_COLOR[item.severity] || "bi-info-circle-fill";
            return (
                '<div class="panda-insight-card panda-severity-' + escapeHtml(item.severity) + '">' +
                    '<i class="bi ' + icon + ' panda-insight-icon"></i>' +
                    '<div>' +
                        '<div class="panda-insight-title">' + escapeHtml(item.title) + '</div>' +
                        '<div class="panda-insight-message">' + escapeHtml(item.message) + '</div>' +
                    '</div>' +
                '</div>'
            );
        }).join("");

        badge.textContent = insights.length > 99 ? "99+" : String(insights.length);
        badge.hidden = false;
    }

    // ------------------------------------------------------------------
    // Suggested questions
    // ------------------------------------------------------------------

    function loadSuggestions() {
        jsonFetch(questionsUrl, { method: "GET", headers: {} }).then(function (result) {
            if (!result.ok) return;
            renderSuggestions(result.data.questions || []);
        }).catch(function () {});
    }

    function renderSuggestions(questions) {
        suggestionsEl.innerHTML = questions.map(function (question) {
            return '<button type="button" class="panda-suggestion-chip">' + escapeHtml(question) + '</button>';
        }).join("");
    }

    suggestionsEl.addEventListener("click", function (event) {
        var chip = event.target.closest(".panda-suggestion-chip");
        if (!chip) return;
        sendMessage(chip.textContent);
    });

    // ------------------------------------------------------------------
    // Chat messages
    // ------------------------------------------------------------------

    function showChatView() {
        welcome.hidden = true;
        messagesEl.hidden = false;
    }

    function showWelcomeView() {
        welcome.hidden = false;
        messagesEl.hidden = true;
        messagesEl.innerHTML = "";
    }

    function appendMessage(role, content) {
        var bubble = document.createElement("div");
        bubble.className = "panda-bubble panda-bubble-" + (role === "user" ? "user" : "bot");
        bubble.textContent = content;
        messagesEl.appendChild(bubble);
        body.scrollTop = body.scrollHeight;
    }

    function ensureConversation() {
        if (currentConversationId) {
            return Promise.resolve(currentConversationId);
        }
        return jsonFetch(conversationsUrl, { method: "POST" }).then(function (result) {
            if (!result.ok) {
                var error = new Error(result.data.error || "chat_unavailable");
                error.sessionLapse = isSessionLapse(result);
                error.serviceUnavailable = isBackendFailure(result);
                throw error;
            }
            currentConversationId = result.data.conversation.conversation_id;
            return currentConversationId;
        });
    }

    function sendMessage(text) {
        text = (text || "").trim();
        if (!text) return;

        showChatView();
        appendMessage("user", text);
        input.value = "";
        input.style.height = "auto";
        sendBtn.disabled = true;

        ensureConversation().then(function (conversationId) {
            return jsonFetch(conversationsUrl + "/" + conversationId + "/messages", {
                method: "POST",
                body: JSON.stringify({ message: text }),
            });
        }).then(function (result) {
            if (!result.ok) {
                appendMessage("assistant", isSessionLapse(result)
                    ? SESSION_EXPIRED_MESSAGE
                    : isBackendFailure(result)
                        ? SERVICE_UNAVAILABLE_MESSAGE
                        : (result.data.message || "Panda's chat history isn't available right now."));
                return;
            }
            appendMessage("assistant", result.data.assistant_message.content);
        }).catch(function (error) {
            appendMessage("assistant", error && error.sessionLapse
                ? SESSION_EXPIRED_MESSAGE
                : error && error.serviceUnavailable
                    ? SERVICE_UNAVAILABLE_MESSAGE
                    : "Something went wrong reaching Panda. Please try again.");
        }).finally(function () {
            sendBtn.disabled = false;
        });
    }

    form.addEventListener("submit", function (event) {
        event.preventDefault();
        sendMessage(input.value);
    });

    input.addEventListener("keydown", function (event) {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            sendMessage(input.value);
        }
    });

    input.addEventListener("input", function () {
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 96) + "px";
    });

    // ------------------------------------------------------------------
    // New Chat
    // ------------------------------------------------------------------

    newChatBtn.addEventListener("click", function () {
        currentConversationId = null;
        showWelcomeView();
        historyPanel.hidden = true;
    });

    // ------------------------------------------------------------------
    // Chat History
    // ------------------------------------------------------------------

    function loadHistory() {
        historyList.innerHTML = '<li class="panda-history-empty">Loading...</li>';
        jsonFetch(conversationsUrl, { method: "GET", headers: {} }).then(function (result) {
            if (!result.ok) {
                var message = isSessionLapse(result)
                    ? SESSION_EXPIRED_MESSAGE
                    : isBackendFailure(result)
                        ? SERVICE_UNAVAILABLE_MESSAGE
                        : (result.data.message || "Chat history isn't available yet.");
                historyList.innerHTML = '<li class="panda-history-empty">' + escapeHtml(message) + '</li>';
                return;
            }
            renderHistory(result.data.conversations || []);
        }).catch(function () {
            historyList.innerHTML = '<li class="panda-history-empty">Couldn\'t load chat history.</li>';
        });
    }

    function renderHistory(conversations) {
        if (conversations.length === 0) {
            historyList.innerHTML = '<li class="panda-history-empty">No past conversations yet.</li>';
            return;
        }
        historyList.innerHTML = conversations.map(function (item) {
            return (
                '<li class="panda-history-item" data-conversation-id="' + item.conversation_id + '">' +
                    '<div class="panda-history-item-title">' + escapeHtml(item.title || "New conversation") + '</div>' +
                    '<div class="panda-history-item-time">' + escapeHtml(new Date(item.updated_at).toLocaleString()) + '</div>' +
                '</li>'
            );
        }).join("");
    }

    historyList.addEventListener("click", function (event) {
        var item = event.target.closest(".panda-history-item");
        if (!item) return;
        openConversation(item.dataset.conversationId);
    });

    function openConversation(conversationId) {
        jsonFetch(conversationsUrl + "/" + conversationId + "/messages", { method: "GET", headers: {} }).then(function (result) {
            if (!result.ok) return;
            currentConversationId = conversationId;
            showChatView();
            messagesEl.innerHTML = "";
            (result.data.messages || []).forEach(function (message) {
                appendMessage(message.role, message.content);
            });
            historyPanel.hidden = true;
        });
    }

    historyBtn.addEventListener("click", function () {
        historyPanel.hidden = false;
        loadHistory();
    });

    historyCloseBtn.addEventListener("click", function () {
        historyPanel.hidden = true;
    });
});
