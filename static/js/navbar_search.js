document.addEventListener("DOMContentLoaded", function () {

    var container = document.getElementById("globalSearch");
    if (!container) return;

    var input = document.getElementById("globalSearchInput");
    var list = document.getElementById("globalSearchSuggestions");
    var searchUrl = container.dataset.searchUrl;

    // Order matches how groups are rendered in the dropdown.
    var GROUPS = [
        { key: "students", label: "Students", clickable: true },
        { key: "payments", label: "Payments", clickable: true },
        { key: "enquiries", label: "Enquiries", clickable: true },
        { key: "cashbook", label: "Cashbook", clickable: false }
    ];

    var debounceTimer = null;
    var latestRequestId = 0;
    var activeIndex = -1;
    var currentItems = []; // flat list of {type, item, clickable}, headers excluded

    function escapeHtml(value) {
        var div = document.createElement("div");
        div.textContent = value === null || value === undefined ? "" : String(value);
        return div.innerHTML;
    }

    function formatLibraryId(studentId) {
        return "LIB" + String(studentId).padStart(4, "0");
    }

    function formatRupees(amount) {
        var n = Number(amount);
        return "₹" + (isNaN(n) ? "0" : n.toLocaleString("en-IN"));
    }

    function closeList() {
        list.hidden = true;
        list.innerHTML = "";
        activeIndex = -1;
        currentItems = [];
        input.setAttribute("aria-expanded", "false");
    }

    function highlight(index) {
        var nodes = list.querySelectorAll(".navbar-search-suggestion");
        for (var i = 0; i < nodes.length; i++) {
            nodes[i].classList.remove("active");
            nodes[i].setAttribute("aria-selected", "false");
        }
        if (index >= 0 && index < nodes.length) {
            nodes[index].classList.add("active");
            nodes[index].setAttribute("aria-selected", "true");
            nodes[index].scrollIntoView({ block: "nearest" });
        }
        activeIndex = index;
    }

    function renderRow(type, item, clickable, flatIndex) {
        var title, meta;

        if (type === "students") {
            title = escapeHtml(item.full_name);
            meta = formatLibraryId(item.student_id) + " &middot; " + escapeHtml(item.mobile || "—");
        } else if (type === "payments") {
            title = escapeHtml(item.receipt_number);
            meta = escapeHtml(item.full_name || "—") + " &middot; " + formatRupees(item.amount_paid);
        } else if (type === "enquiries") {
            title = escapeHtml(item.full_name);
            meta = escapeHtml(item.mobile || "—") + " &middot; " + escapeHtml(item.purpose || "—");
        } else {
            title = escapeHtml(item.category || "Cashbook entry");
            meta = escapeHtml(item.person || "—") + " &middot; " + formatRupees(item.amount);
        }

        var classes = "navbar-search-suggestion" + (clickable ? "" : " navbar-search-suggestion-disabled");

        return (
            '<li class="' + classes + '" role="option" aria-selected="false" ' +
                'data-index="' + flatIndex + '" data-type="' + type + '">' +
                '<div class="navbar-search-suggestion-title">' + title + '</div>' +
                '<div class="navbar-search-suggestion-meta">' + meta + '</div>' +
            '</li>'
        );
    }

    function renderItems(data) {
        currentItems = [];
        activeIndex = -1;

        var html = "";

        GROUPS.forEach(function (group) {
            var items = (data && data[group.key]) || [];
            if (items.length === 0) return;

            html += '<li class="navbar-search-group-header">' + escapeHtml(group.label) + '</li>';

            items.forEach(function (item) {
                var flatIndex = currentItems.length;
                currentItems.push({ type: group.key, item: item, clickable: group.clickable });
                html += renderRow(group.key, item, group.clickable, flatIndex);
            });
        });

        if (currentItems.length === 0) {
            list.innerHTML = '<li class="navbar-search-suggestion-empty">No results found</li>';
            list.hidden = false;
            input.setAttribute("aria-expanded", "true");
            return;
        }

        list.innerHTML = html;
        list.hidden = false;
        input.setAttribute("aria-expanded", "true");
    }

    function selectItem(entry) {
        if (!entry || !entry.clickable) return;

        if (entry.type === "students") {
            window.location.href = "/students/view/" + encodeURIComponent(entry.item.student_id);
        } else if (entry.type === "payments") {
            window.location.href = "/payments/receipt/" + encodeURIComponent(entry.item.payment_id);
        } else if (entry.type === "enquiries") {
            window.location.href = "/enquiries/view/" + encodeURIComponent(entry.item.enquiry_id);
        }
        // Cashbook entries have no single-record view page yet (TD-56) -
        // clickable is false for that group, so this is never reached.
    }

    input.addEventListener("input", function () {
        var query = input.value.trim();
        clearTimeout(debounceTimer);

        if (!query) {
            closeList();
            return;
        }

        debounceTimer = setTimeout(function () {
            var requestId = ++latestRequestId;
            fetch(searchUrl + "?q=" + encodeURIComponent(query))
                .then(function (response) { return response.ok ? response.json() : {}; })
                .then(function (data) {
                    if (requestId !== latestRequestId) return; // a newer keystroke already fired
                    renderItems(data);
                })
                .catch(function () {
                    if (requestId !== latestRequestId) return;
                    closeList();
                });
        }, 250);
    });

    input.addEventListener("keydown", function (event) {
        if (list.hidden || currentItems.length === 0) return;

        if (event.key === "ArrowDown") {
            event.preventDefault();
            highlight((activeIndex + 1) % currentItems.length);
        } else if (event.key === "ArrowUp") {
            event.preventDefault();
            highlight((activeIndex - 1 + currentItems.length) % currentItems.length);
        } else if (event.key === "Enter") {
            if (activeIndex >= 0) {
                event.preventDefault();
                selectItem(currentItems[activeIndex]);
            }
        } else if (event.key === "Escape") {
            closeList();
        }
    });

    list.addEventListener("click", function (event) {
        var row = event.target.closest(".navbar-search-suggestion");
        if (!row) return;
        var index = parseInt(row.dataset.index, 10);
        if (isNaN(index)) return;
        selectItem(currentItems[index]);
    });

    document.addEventListener("click", function (event) {
        if (!container.contains(event.target)) {
            closeList();
        }
    });
});
