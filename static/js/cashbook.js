document.addEventListener("DOMContentLoaded", () => {

    const typeSelect = document.getElementById("transactionType");

    const categorySelect = document.getElementById("transactionCategory");

    // Manual entries only cover what isn't already automatic (Admission,
    // Membership Fee and Renewal all post to Cashbook on their own).
    const incomeCategories = [

        "Misc Income"

    ];

    const expenseCategories = [

        "Electricity",

        "Internet",

        "Furniture",

        "Books",

        "Salary",

        "Repairs",

        "Misc Expenses"

    ];

    function loadCategories(type){

        const personLabel = document.getElementById("personLabel");

        const personInput = document.getElementById("personInput");

        categorySelect.innerHTML = "";

        if(type==="Income"){

            personLabel.innerText="Student";
            personInput.placeholder="Rahul Sharma";

        }
        else{

            personLabel.innerText="Paid To";
            personInput.placeholder="Electricity Board";

        }

        let list = type === "Income"
            ? incomeCategories
            : expenseCategories;

        list.forEach(item=>{

            let option = document.createElement("option");

            option.value = item;

            option.textContent = item;

            categorySelect.appendChild(option);

        });

    }

    if (typeSelect && categorySelect) {

        loadCategories(typeSelect.value);

        typeSelect.addEventListener("change",()=>{

            loadCategories(typeSelect.value);

        });

    }

});

document.addEventListener("DOMContentLoaded", () => {

    const transactionForm = document.getElementById("transactionForm");

    transactionForm?.addEventListener("submit", (event) => {

        const submitBtn = transactionForm.querySelector("button[type='submit']");

        if (transactionForm.dataset.submitting === "true") {
            event.preventDefault();
            return;
        }

        transactionForm.dataset.submitting = "true";

        if (submitBtn) {
            submitBtn.disabled = true;
        }

    });

});

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
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: { position: "bottom" }
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

    renderChart(
        "expenseCategoryChart",
        "doughnut",
        chartData.expenseCategory,
        {
            responsive: true,
            plugins: {
                legend: { position: "bottom" }
            }
        }
    );

    renderChart(
        "revenueSourceChart",
        "doughnut",
        chartData.revenueSource,
        {
            responsive: true,
            plugins: {
                legend: { position: "bottom" }
            }
        }
    );

    renderChart(
        "paymentMethodChart",
        "doughnut",
        chartData.paymentMethod,
        {
            responsive: true,
            plugins: {
                legend: { position: "bottom" }
            }
        }
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

    document.querySelectorAll(".cashbook-edit-btn").forEach((btn) => {

        btn.addEventListener("click", () => {

            const row = btn.closest("tr");
            const form = document.getElementById("editTransactionForm");
            if (!row || !editModal || !form) return;

            const template = form.dataset.urlTemplate;
            form.action = template.replace(/0$/, row.dataset.id);

            document.getElementById("editCategory").value = row.dataset.category || "";
            document.getElementById("editAmount").value = row.dataset.amount || "";
            document.getElementById("editPaymentMethod").value = row.dataset.paymentMethod || "Cash";
            document.getElementById("editDate").value = row.dataset.date || "";
            document.getElementById("editPerson").value = row.dataset.person || "";
            document.getElementById("editDescription").value = row.dataset.description || "";

            editModal.show();

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
