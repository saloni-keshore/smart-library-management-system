document.addEventListener("DOMContentLoaded", function () {

    var container = document.getElementById("aiStudentSearch");
    if (!container) return;

    var input = document.getElementById("aiSearchInput");
    var list = document.getElementById("aiSuggestions");
    var searchUrl = container.dataset.searchUrl;

    var debounceTimer = null;
    var latestRequestId = 0;
    var activeIndex = -1;
    var currentItems = [];

    function escapeHtml(value) {
        var div = document.createElement("div");
        div.textContent = value === null || value === undefined ? "" : String(value);
        return div.innerHTML;
    }

    function formatLibraryId(studentId) {
        return "LIB" + String(studentId).padStart(4, "0");
    }

    function closeList() {
        list.hidden = true;
        list.innerHTML = "";
        activeIndex = -1;
        currentItems = [];
        input.setAttribute("aria-expanded", "false");
    }

    function highlight(index) {
        var nodes = list.querySelectorAll(".ai-suggestion");
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

    function renderItems(items) {
        currentItems = items;
        activeIndex = -1;

        if (items.length === 0) {
            list.innerHTML = '<li class="ai-suggestion-empty">No students found</li>';
            list.hidden = false;
            input.setAttribute("aria-expanded", "true");
            return;
        }

        list.innerHTML = items.map(function (item, index) {
            return (
                '<li class="ai-suggestion" role="option" aria-selected="false" ' +
                    'data-index="' + index + '" data-student-id="' + item.student_id + '">' +
                    '<div class="ai-suggestion-name">' + escapeHtml(item.full_name) + '</div>' +
                    '<div class="ai-suggestion-meta">' +
                        '<span>' + formatLibraryId(item.student_id) + '</span>' +
                        '<span>' + escapeHtml(item.mobile || "—") + '</span>' +
                        '<span>' + escapeHtml(item.plan_name || "No membership yet") + '</span>' +
                    '</div>' +
                '</li>'
            );
        }).join("");
        list.hidden = false;
        input.setAttribute("aria-expanded", "true");
    }

    function selectStudent(studentId) {
        window.location.href = "/ai-center/?student_id=" + encodeURIComponent(studentId);
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
                .then(function (response) { return response.ok ? response.json() : []; })
                .then(function (items) {
                    if (requestId !== latestRequestId) return; // a newer keystroke already fired
                    renderItems(items);
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
                selectStudent(currentItems[activeIndex].student_id);
            }
        } else if (event.key === "Escape") {
            closeList();
        }
    });

    list.addEventListener("click", function (event) {
        var item = event.target.closest(".ai-suggestion");
        if (!item || !item.dataset.studentId) return;
        selectStudent(item.dataset.studentId);
    });

    document.addEventListener("click", function (event) {
        if (!container.contains(event.target)) {
            closeList();
        }
    });
});
