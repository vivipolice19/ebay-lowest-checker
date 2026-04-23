function showToast(message, type) {
    type = type || "info";
    var existing = document.querySelector(".toast");
    if (existing) existing.remove();

    var toast = document.createElement("div");
    toast.className = "toast toast-" + type;
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(function() {
        toast.remove();
    }, 4000);
}

function apiCall(url, method, data) {
    var options = {
        method: method || "GET",
        headers: { "Content-Type": "application/json" }
    };
    if (data) {
        options.body = JSON.stringify(data);
    }
    return fetch(url, options).then(function(r) { return r.json(); });
}

function triggerSync() {
    showToast("スプレッドシート同期中...", "info");
    apiCall("/api/sheets/sync", "POST").then(function(result) {
        if (result.success) {
            showToast(result.message || "同期開始", "success");
            setTimeout(function() { location.reload(); }, 3000);
        } else {
            showToast(result.error || "同期に失敗しました", "error");
        }
    });
}

function toggleSync(action) {
    apiCall("/api/sheets/" + action, "POST").then(function(result) {
        if (result.success) {
            showToast(action === "start" ? "自動同期を開始しました" : "自動同期を停止しました", "success");
            setTimeout(function() { location.reload(); }, 500);
        } else {
            showToast(result.error || "操作に失敗しました", "error");
        }
    });
}

function toggleMonitor(action) {
    apiCall("/api/monitor/" + action, "POST").then(function(result) {
        showToast(action === "start" ? "売切れ監視を開始しました" : "売切れ監視を停止しました", "success");
        setTimeout(function() { location.reload(); }, 500);
    });
}

function toggleProfitMonitor(action) {
    apiCall("/api/profit/" + action, "POST").then(function(result) {
        showToast(action === "start" ? "利益監視を開始しました" : "利益監視を停止しました", "success");
        setTimeout(function() { location.reload(); }, 500);
    });
}

function runProfitCheck() {
    showToast("利益チェック実行中...", "info");
    apiCall("/api/profit/check", "POST").then(function(result) {
        if (result.success) {
            var r = result.result;
            var msg = "チェック完了";
            if (r.alerts && r.alerts.length > 0) msg += " - アラート" + r.alerts.length + "件";
            if (r.auto_stopped && r.auto_stopped.length > 0) msg += " - 自動停止" + r.auto_stopped.length + "件";
            showToast(msg, r.alerts && r.alerts.length > 0 ? "error" : "success");
            setTimeout(function() { location.reload(); }, 1000);
        }
    });
}

function updateExchangeRate() {
    showToast("為替レート取得中...", "info");
    apiCall("/api/exchange_rate/update", "POST").then(function(result) {
        if (result.success) {
            showToast("為替レート更新: 1 USD = " + result.rate.toFixed(2) + " JPY", "success");
            var el = document.getElementById("exchange-rate");
            if (el) el.textContent = "1 USD = " + result.rate.toFixed(2) + " JPY";
        } else {
            showToast("為替レート取得に失敗しました", "error");
        }
    });
}

function refreshProducts() {
    location.reload();
}

function refreshSyncStatus() {
    fetch("/api/sheets/status")
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var el = document.getElementById("sync-status");
            var btnEl = document.getElementById("sync-toggle-btn");
            var lastSyncEl = document.getElementById("last-sync-time");
            if (el) {
                if (data.running) {
                    el.textContent = "実行中";
                    el.className = "status-active";
                    if (btnEl) btnEl.innerHTML = '<button class="btn btn-sm btn-danger" onclick="toggleSync(\'stop\')">停止</button>';
                } else {
                    el.textContent = "停止中";
                    el.className = "status-inactive";
                    if (btnEl) btnEl.innerHTML = '<button class="btn btn-sm btn-success" onclick="toggleSync(\'start\')">開始</button>';
                }
            }
            if (lastSyncEl && data.last_sync) {
                lastSyncEl.textContent = data.last_sync;
            }
        })
        .catch(function() {});
}

if (document.getElementById("sync-status")) {
    setInterval(refreshSyncStatus, 5000);
    setTimeout(refreshSyncStatus, 2000);
}

function saveSettings(e) {
    e.preventDefault();
    var data = {
        warning_threshold: document.getElementById("warning-threshold").value,
        alert_threshold: document.getElementById("alert-threshold").value,
        auto_stop_threshold: document.getElementById("auto-stop-threshold").value,
        ebay_fee: document.getElementById("ebay-fee").value,
        shipping_usd: document.getElementById("shipping-usd").value,
        other_expenses: document.getElementById("other-expenses").value,
        auto_stop_enabled: document.getElementById("auto-stop-enabled").checked ? "true" : "false"
    };
    apiCall("/api/settings", "POST", data).then(function(result) {
        if (result.success) {
            showToast("設定を保存しました", "success");
        }
    });
}

function saveLineSettings(e) {
    e.preventDefault();
    var data = {
        line_token: document.getElementById("line-token").value
    };
    apiCall("/api/settings", "POST", data).then(function(result) {
        if (result.success) {
            showToast("LINE設定を保存しました", "success");
        }
    });
}

function testLineNotify() {
    var token = document.getElementById("line-token").value;
    if (!token) {
        showToast("トークンを入力してください", "error");
        return;
    }
    apiCall("/api/settings", "POST", { line_token: token }).then(function() {
        showToast("テスト通知を送信しました", "info");
    });
}

function saveBrowseApiSettings(e) {
    e.preventDefault();
    var data = {
        ebay_client_id: document.getElementById("ebay-client-id").value,
        ebay_client_secret: document.getElementById("ebay-client-secret").value
    };
    apiCall("/api/settings", "POST", data).then(function(result) {
        if (result.success) {
            showToast("Browse API設定を保存しました", "success");
            setTimeout(function() { location.reload(); }, 1000);
        } else {
            showToast(result.error || "保存に失敗しました", "error");
        }
    });
}

function saveEbaySettings(e) {
    e.preventDefault();
    var tokenEl = document.getElementById("ebay-oauth-token");
    var data = {
        ebay_oauth_token: tokenEl ? tokenEl.value : ""
    };
    apiCall("/api/settings", "POST", data).then(function(result) {
        if (result.success) {
            showToast("トークンを保存しました", "success");
            setTimeout(function() { location.reload(); }, 1000);
        } else {
            showToast(result.error || "保存に失敗しました", "error");
        }
    });
}

function saveSheetsSettings(e) {
    e.preventDefault();
    var data = {
        sheet_id: document.getElementById("sheet-id").value,
        creds_path: document.getElementById("creds-path").value,
        sync_interval: document.getElementById("sync-interval").value
    };

    if (!data.sheet_id) {
        showToast("スプレッドシートURLを入力してください", "error");
        return;
    }

    apiCall("/api/settings", "POST", data).then(function(result) {
        if (result.success) {
            showToast("設定を保存しました。自動同期を開始します。", "success");
            setTimeout(function() { location.reload(); }, 1000);
        } else {
            showToast(result.error || "保存に失敗しました", "error");
        }
    });
}
