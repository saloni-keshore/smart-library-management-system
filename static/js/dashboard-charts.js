(function () {
    "use strict";

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

    document.addEventListener("DOMContentLoaded", initChartSkeletons);
})();
