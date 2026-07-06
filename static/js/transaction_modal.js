// Shared "Add Transaction" modal behavior - reused by the Cashbook page
// (New Transaction button + Floating Action Button) and the Dashboard
// (Add Income / Add Expense / Add Fine / Record Donation quick actions).
document.addEventListener("DOMContentLoaded", () => {

    const modalEl = document.getElementById("transactionModal");
    const typeSelect = document.getElementById("transactionType");
    const incomeCategorySelect = document.getElementById("incomeCategorySelect");
    const expenseCategorySelect = document.getElementById("expenseCategorySelect");
    const personLabel = document.getElementById("personLabel");
    const personInput = document.getElementById("personInput");
    const dateInput = document.getElementById("transactionDate");
    const redirectInput = document.getElementById("transactionRedirectTo");

    if (!modalEl || !typeSelect) {
        return;
    }

    const modal = new bootstrap.Modal(modalEl);

    function activeCategorySelect(type) {
        return type === "Income" ? incomeCategorySelect : expenseCategorySelect;
    }

    function syncCategoryVisibility() {

        const type = typeSelect.value;

        [incomeCategorySelect, expenseCategorySelect].forEach((select) => {
            if (!select) return;
            const isActive = select.dataset.type === type;
            select.classList.toggle("d-none", !isActive);
            select.disabled = !isActive;
        });

        if (personLabel && personInput) {
            if (type === "Income") {
                personLabel.innerText = "Student";
                personInput.placeholder = "Rahul Sharma";
            } else {
                personLabel.innerText = "Paid To";
                personInput.placeholder = "Electricity Board";
            }
        }
    }

    typeSelect.addEventListener("change", syncCategoryVisibility);
    syncCategoryVisibility();

    function openTransactionModal({ type, category, redirect }) {

        typeSelect.value = type || "Income";
        syncCategoryVisibility();

        if (category) {
            const select = activeCategorySelect(typeSelect.value);
            if (select) select.value = category;
        }

        if (redirectInput) {
            redirectInput.value = redirect || "cashbook";
        }

        if (dateInput && !dateInput.value) {
            dateInput.value = new Date().toISOString().slice(0, 10);
        }

        modal.show();
    }

    document.querySelectorAll(".cashbook-fab-option, .quick-add-trigger").forEach((trigger) => {

        trigger.addEventListener("click", () => {
            openTransactionModal({
                type: trigger.dataset.presetType,
                category: trigger.dataset.presetCategory,
                redirect: trigger.dataset.presetRedirect
            });
        });

    });

    // Default "New Transaction" button (Cashbook page) - no preset, defaults
    // to Income and stays on the Cashbook page after saving.
    document.querySelectorAll("[data-bs-target='#transactionModal']").forEach((trigger) => {
        if (trigger.classList.contains("cashbook-fab-option") || trigger.classList.contains("quick-add-trigger")) {
            return;
        }
        trigger.addEventListener("click", () => {
            if (redirectInput) redirectInput.value = "cashbook";
            if (dateInput && !dateInput.value) {
                dateInput.value = new Date().toISOString().slice(0, 10);
            }
        });
    });

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
