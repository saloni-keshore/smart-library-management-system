document.addEventListener("DOMContentLoaded", function () {

    // ---- inline "ⓘ" help tooltips: hover, tap or keyboard focus ----
    var tips = document.querySelectorAll(".ai-info-tip");

    function closeAllTips(except) {
        tips.forEach(function (tip) {
            if (tip !== except) tip.classList.remove("ai-info-tip-open");
        });
    }

    tips.forEach(function (tip) {
        tip.addEventListener("click", function (event) {
            // Stops the click reaching the <label> this icon sits inside,
            // which would otherwise shift focus to the number input instead
            // of just opening the tooltip.
            event.preventDefault();
            event.stopPropagation();
            var isOpen = tip.classList.contains("ai-info-tip-open");
            closeAllTips();
            if (!isOpen) tip.classList.add("ai-info-tip-open");
        });
        tip.addEventListener("mouseenter", function () {
            closeAllTips(tip);
            tip.classList.add("ai-info-tip-open");
        });
        tip.addEventListener("mouseleave", function () {
            tip.classList.remove("ai-info-tip-open");
        });
        tip.addEventListener("focus", function () {
            closeAllTips(tip);
            tip.classList.add("ai-info-tip-open");
        });
        tip.addEventListener("blur", function () {
            tip.classList.remove("ai-info-tip-open");
        });
        tip.addEventListener("keydown", function (event) {
            if (event.key === "Escape") tip.classList.remove("ai-info-tip-open");
        });
    });

    document.addEventListener("click", function () {
        closeAllTips();
    });

    // ---- live preview bars - cosmetic only, the server re-validates on save ----
    function clamp(value, min, max) {
        return Math.min(max, Math.max(min, value));
    }

    var highInput = document.getElementById("high_risk_max");
    var lowInput = document.getElementById("low_risk_min");
    var segHigh = document.getElementById("rangeSegHigh");
    var segMedium = document.getElementById("rangeSegMedium");
    var segLow = document.getElementById("rangeSegLow");
    var scaleHigh = document.getElementById("rangeScaleHighVal");
    var scaleLow = document.getElementById("rangeScaleLowVal");

    function updateRangeBar() {
        var high = clamp(parseInt(highInput.value, 10) || 0, 0, 100);
        var low = clamp(parseInt(lowInput.value, 10) || 0, 0, 100);
        if (low < high) low = high;

        segHigh.style.width = high + "%";
        segMedium.style.width = (low - high) + "%";
        segLow.style.width = (100 - low) + "%";
        scaleHigh.textContent = high;
        scaleLow.textContent = low;
    }

    if (highInput && lowInput && segHigh && segMedium && segLow) {
        highInput.addEventListener("input", updateRangeBar);
        lowInput.addEventListener("input", updateRangeBar);
    }

    var weightFields = [
        { input: "weight_payment_delay", fill: "weightFillPayment", pct: "weightPctPayment" },
        { input: "weight_renewal_history", fill: "weightFillRenewal", pct: "weightPctRenewal" },
        { input: "weight_membership_duration", fill: "weightFillMembership", pct: "weightPctMembership" }
    ];
    var totalRow = document.getElementById("weightTotalRow");
    var totalFill = document.getElementById("weightFillTotal");
    var totalPct = document.getElementById("weightPctTotal");

    function updateWeightBars() {
        var total = 0;

        weightFields.forEach(function (field) {
            var input = document.getElementById(field.input);
            var fill = document.getElementById(field.fill);
            var pct = document.getElementById(field.pct);
            if (!input || !fill || !pct) return;

            var value = clamp(parseInt(input.value, 10) || 0, 0, 100);
            fill.style.width = value + "%";
            pct.textContent = value + "%";
            total += value;
        });

        if (totalFill && totalPct && totalRow) {
            totalFill.style.width = clamp(total, 0, 100) + "%";
            totalPct.textContent = total + "%";
            totalRow.classList.toggle("ai-weight-total-off", total !== 100);
        }
    }

    var weightInputs = weightFields
        .map(function (field) { return document.getElementById(field.input); })
        .filter(Boolean);

    weightInputs.forEach(function (input) {
        input.addEventListener("input", updateWeightBars);
    });
});
