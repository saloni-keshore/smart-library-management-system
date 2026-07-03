(function () {
    "use strict";

    function addReceiptRow(container, label, value) {
        var row = document.createElement("div");
        row.className = "receipt-row";

        var labelEl = document.createElement("span");
        labelEl.textContent = label;

        var valueEl = document.createElement("strong");
        valueEl.textContent = value;

        row.appendChild(labelEl);
        row.appendChild(valueEl);
        container.appendChild(row);
    }

    document.addEventListener("DOMContentLoaded", function () {

        var animatedBars = Array.prototype.slice.call(
            document.querySelectorAll(".animated-bar")
        );

        if (animatedBars.length) {
            window.setTimeout(function () {
                animatedBars.forEach(function (bar) {
                    var target = bar.dataset.targetWidth || 0;
                    bar.style.width = target + "%";
                });
            }, 150);
        }

        var table = document.getElementById("membershipDistributionTable");

        if (table) {

            var rows = Array.prototype.slice.call(
                table.querySelectorAll("tbody tr[data-status]")
            );
            var chips = Array.prototype.slice.call(
                document.querySelectorAll(".filter-chip")
            );
            var searchInput = document.getElementById("membershipSearchInput");
            var noResults = document.getElementById("membershipNoResults");
            var rowCount = document.getElementById("membershipRowCount");

            var activeFilter = "all";

            var applyFilters = function () {
                var term = ((searchInput && searchInput.value) || "").trim().toLowerCase();
                var visibleCount = 0;

                rows.forEach(function (row) {
                    var matchesFilter =
                        activeFilter === "all" ||
                        row.dataset.status === activeFilter ||
                        row.dataset.plan === activeFilter;

                    var matchesSearch =
                        !term || row.dataset.search.indexOf(term) !== -1;

                    var visible = matchesFilter && matchesSearch;
                    row.classList.toggle("d-none", !visible);

                    if (visible) {
                        visibleCount++;
                    }
                });

                if (noResults) {
                    noResults.classList.toggle(
                        "d-none",
                        visibleCount !== 0 || rows.length === 0
                    );
                }

                if (rowCount) {
                    rowCount.textContent = visibleCount + " of " + rows.length + " records";
                }
            };

            chips.forEach(function (chip) {
                chip.addEventListener("click", function () {
                    chips.forEach(function (c) {
                        c.classList.remove("active");
                    });
                    chip.classList.add("active");
                    activeFilter = chip.dataset.filter;
                    applyFilters();
                });
            });

            if (searchInput) {
                searchInput.addEventListener("input", applyFilters);
            }

            applyFilters();
        }

        var receiptModal = document.getElementById("receiptModal");

        if (receiptModal) {

            receiptModal.addEventListener("show.bs.modal", function (event) {

                var btn = event.relatedTarget;
                if (!btn) return;

                var body = document.getElementById("receiptModalBody");
                if (!body) return;

                body.innerHTML = "";

                var d = btn.dataset;

                addReceiptRow(body, "Receipt No.", d.receiptNumber);
                addReceiptRow(body, "Student", d.student);
                addReceiptRow(body, "Library ID", d.libraryId);
                addReceiptRow(body, "Mobile", d.mobile);
                addReceiptRow(body, "Plan", d.plan);
                addReceiptRow(body, "Join Date", d.joinDate);
                addReceiptRow(body, "Expiry Date", d.endDate);

                body.appendChild(document.createElement("hr"));

                addReceiptRow(body, "Payment Mode", d.paymentMode);
                addReceiptRow(body, "Payment Date", d.paymentDate);
                addReceiptRow(body, "Last Amount Paid", "₹" + d.lastAmount);
                addReceiptRow(body, "Total Paid", "₹" + d.paidAmount);
                addReceiptRow(body, "Pending", "₹" + d.pendingAmount);
            });
        }

        var printBtn = document.getElementById("receiptPrintBtn");

        if (printBtn) {
            printBtn.addEventListener("click", function () {
                window.print();
            });
        }

    });
})();
