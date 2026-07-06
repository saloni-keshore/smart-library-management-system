// Category select toggling + submit-guard for the "New Transaction" modal
// now live in transaction_modal.js, shared with the Dashboard quick actions.

document.addEventListener("DOMContentLoaded", () => {

    const chartData = window.cashbookChartData || {};

    function hasData(data){

        if(!data || !data.labels || data.labels.length === 0){
            return false;
        }

        return data.datasets.some(
            ds => (ds.data || []).some(value => value)
        );

    }

    function showEmptyState(canvas){

        canvas.style.display = "none";

        const message = document.createElement("p");

        message.className = "text-muted text-center py-5 mb-0";
        message.textContent = "No transaction data available";

        canvas.insertAdjacentElement("afterend", message);

    }

    function renderChart(canvasId, type, data, options){

        const canvas = document.getElementById(canvasId);

        if(!canvas){
            return;
        }

        if(!hasData(data)){
            showEmptyState(canvas);
            return;
        }

        new Chart(canvas, { type, data, options });

    }

    renderChart(
        "incomeExpenseChart",
        "line",
        chartData.incomeExpense,
        {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: { position: "bottom", labels: { boxWidth: 12, padding: 16 } }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: value => "₹" + value.toLocaleString("en-IN")
                    }
                }
            },
            elements: {
                point: { radius: 3 }
            }
        }
    );

    const donutOptions = {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "68%",
        plugins: {
            legend: { position: "bottom", labels: { boxWidth: 12, padding: 16 } }
        }
    };

    renderChart(
        "expenseCategoryChart",
        "doughnut",
        chartData.expenseCategory,
        donutOptions
    );

    renderChart(
        "revenueSourceChart",
        "doughnut",
        chartData.revenueSource,
        donutOptions
    );

    renderChart(
        "paymentMethodChart",
        "doughnut",
        chartData.paymentMethod,
        donutOptions
    );

});

// Transaction details (View) modal + Edit modal
document.addEventListener("DOMContentLoaded", () => {

    const detailsModalEl = document.getElementById("transactionDetailsModal");
    const editModalEl = document.getElementById("editTransactionModal");

    const detailsModal = detailsModalEl ? new bootstrap.Modal(detailsModalEl) : null;
    const editModal = editModalEl ? new bootstrap.Modal(editModalEl) : null;

    const formatAmount = (row) => {
        const amount = parseFloat(row.dataset.amount || "0");
        const sign = row.dataset.type === "Income" ? "+" : "−";
        return `${sign} ₹${amount.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
    };

    document.querySelectorAll(".cashbook-view-btn").forEach((btn) => {

        btn.addEventListener("click", () => {

            const row = btn.closest("tr");
            if (!row || !detailsModal) return;

            document.getElementById("detailType").textContent = row.dataset.type || "—";
            document.getElementById("detailCategory").textContent = row.dataset.category || "—";
            document.getElementById("detailPerson").textContent = row.dataset.person || "—";
            document.getElementById("detailPaymentMethod").textContent = row.dataset.paymentMethod || "—";
            document.getElementById("detailAmount").textContent = formatAmount(row);
            document.getElementById("detailDate").textContent = row.dataset.date || "—";
            document.getElementById("detailReferenceId").textContent = row.dataset.referenceId || "—";
            document.getElementById("detailSource").textContent = row.dataset.source || "—";
            document.getElementById("detailCreatedBy").textContent = row.dataset.createdBy || "—";
            document.getElementById("detailDescription").textContent = row.dataset.description || "—";

            detailsModal.show();

        });

    });

    const editIncomeCategorySelect = document.getElementById("editIncomeCategorySelect");
    const editExpenseCategorySelect = document.getElementById("editExpenseCategorySelect");

    document.querySelectorAll(".cashbook-edit-btn").forEach((btn) => {

        btn.addEventListener("click", () => {

            const row = btn.closest("tr");
            const form = document.getElementById("editTransactionForm");
            if (!row || !editModal || !form) return;

            const template = form.dataset.urlTemplate;
            form.action = template.replace(/0$/, row.dataset.id);

            const type = row.dataset.type;

            [editIncomeCategorySelect, editExpenseCategorySelect].forEach((select) => {
                if (!select) return;
                const isActive = select.dataset.type === type;
                select.classList.toggle("d-none", !isActive);
                select.disabled = !isActive;
                if (isActive) select.value = row.dataset.category || "";
            });

            document.getElementById("editAmount").value = row.dataset.amount || "";
            document.getElementById("editPaymentMethod").value = row.dataset.paymentMethod || "Cash";
            document.getElementById("editDate").value = row.dataset.date || "";
            document.getElementById("editPerson").value = row.dataset.person || "";
            document.getElementById("editDescription").value = row.dataset.description || "";

            editModal.show();

        });

    });

});

// Date range preset - reveal the raw From/To inputs only for "Custom".
document.addEventListener("DOMContentLoaded", () => {

    const presetSelect = document.getElementById("datePresetSelect");
    const customFields = document.querySelectorAll(".cashbook-custom-date");

    presetSelect?.addEventListener("change", () => {

        const isCustom = presetSelect.value === "custom";

        customFields.forEach((field) => {
            field.classList.toggle("d-none", !isCustom);
        });

    });

});

// Loading state while filters are applied (full-page GET navigation)
document.addEventListener("DOMContentLoaded", () => {

    const filterForm = document.getElementById("cashbookFilterForm");
    const overlay = document.getElementById("cashbookLoadingOverlay");

    filterForm?.addEventListener("submit", () => {
        overlay?.classList.remove("d-none");
    });

});
