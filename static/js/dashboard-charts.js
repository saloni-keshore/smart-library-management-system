(function () {
    "use strict";

    // ---- Skeleton reveal (unchanged behaviour) --------------------------

    function revealStage(stage) {
        if (stage.classList.contains("is-loaded")) return;
        stage.classList.add("is-loaded");
    }

    function initChartSkeletons() {
        var stages = document.querySelectorAll("[data-chart-stage]");

        stages.forEach(function (stage) {
            var delay = parseInt(stage.dataset.revealDelay, 10) || 800;

            window.setTimeout(function () {
                revealStage(stage);
            }, delay);
        });
    }

    // Exposed so real chart-rendering code can reveal a chart the moment
    // its data actually arrives, instead of waiting on the simulated timer.
    window.revealDashboardChart = function (stageEl) {
        var stage = typeof stageEl === "string"
            ? document.querySelector(stageEl)
            : stageEl;

        if (stage) {
            revealStage(stage);
        }
    };

    // ---- Shared helpers -------------------------------------------------

    function hasChartData(chartData) {
        return chartData &&
            Array.isArray(chartData.labels) &&
            chartData.labels.length > 0;
    }

    function showEmptyState(canvas, message) {
        canvas.style.display = "none";
        var text = document.createElement("p");
        text.className = "chart-empty-text text-muted small mb-0 text-center";
        text.textContent = message;
        canvas.insertAdjacentElement("afterend", text);
    }

    var DOUGHNUT_OPTIONS = {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "58%",
        plugins: {
            legend: {
                position: "bottom",
                labels: { boxWidth: 10, font: { size: 11 } }
            }
        }
    };

    // ---- Revenue Overview (line, with This Year / Last Year switch) -----

    var revenueChart = null;

    function revenueLineOptions() {
        return {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: { legend: { display: false } },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: function (value) {
                            return "₹" + value.toLocaleString("en-IN");
                        }
                    }
                }
            },
            elements: { point: { radius: 3 } }
        };
    }

    function initRevenueChart() {
        var canvas = document.getElementById("revenue-chart-canvas");
        if (!canvas || typeof Chart === "undefined") return;

        var chartData = window.dashboardRevenueChart;
        if (!chartData) return;

        revenueChart = new Chart(canvas, {
            type: "line",
            data: chartData,
            options: revenueLineOptions()
        });

        var select = document.getElementById("revenue-period-select");
        if (!select) return;

        select.addEventListener("change", function () {
            fetch("/dashboard/revenue-chart?period=" + encodeURIComponent(select.value))
                .then(function (response) { return response.json(); })
                .then(function (data) {
                    if (data && data.datasets) {
                        revenueChart.data = data;
                        revenueChart.update();
                    }
                });
        });
    }

    // ---- Membership distribution doughnuts -----------------------------

    function initDoughnut(canvasId, chartData, emptyMessage) {
        var canvas = document.getElementById(canvasId);
        if (!canvas || typeof Chart === "undefined") return;

        if (!hasChartData(chartData)) {
            showEmptyState(canvas, emptyMessage);
            return;
        }

        new Chart(canvas, {
            type: "doughnut",
            data: chartData,
            options: DOUGHNUT_OPTIONS
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        initChartSkeletons();
        initRevenueChart();
        initDoughnut(
            "membership-chart-canvas",
            window.dashboardMembershipChart,
            "No membership data yet"
        );
        initDoughnut(
            "distribution-donut-canvas",
            window.membershipDistributionChart,
            "No membership data yet"
        );
    });
})();
