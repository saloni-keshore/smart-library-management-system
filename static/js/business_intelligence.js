document.addEventListener("DOMContentLoaded", () => {

    const data = window.biChartData || {};

    const STATUS_COLORS = {
        "Excellent": "#16a34a",
        "Good": "#2563eb",
        "Average": "#f59e0b",
        "Needs Attention": "#ef4444"
    };

    function hasSeriesData(chartData){

        if(!chartData || !chartData.labels || chartData.labels.length === 0){
            return false;
        }

        return chartData.datasets.some(
            ds => (ds.data || []).some(value => value)
        );

    }

    function showEmptyState(canvas, message){

        canvas.style.display = "none";

        const text = document.createElement("p");

        text.className = "empty-state-text mb-0";
        text.textContent = message;

        canvas.insertAdjacentElement("afterend", text);

    }

    // --- Business Health Score (circular gauge) ---------------------------

    function renderHealthGauge(){

        const canvas = document.getElementById("biHealthGauge");
        const healthScore = data.healthScore;

        if(!canvas || !healthScore){
            return;
        }

        const score = Math.max(0, Math.min(100, healthScore.score));
        const color = STATUS_COLORS[healthScore.status] || "#2563eb";

        new Chart(canvas, {
            type: "doughnut",
            data: {
                labels: ["Score", "Remaining"],
                datasets: [{
                    data: [score, 100 - score],
                    backgroundColor: [color, "#eef2f7"],
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "78%",
                animation: { animateRotate: true, duration: 900 },
                plugins: {
                    legend: { display: false },
                    tooltip: { enabled: false }
                }
            }
        });

    }

    // --- Revenue Trend (line) ----------------------------------------------

    function renderRevenueTrend(){

        const canvas = document.getElementById("biRevenueTrendChart");
        const chartData = data.revenueTrend;

        if(!canvas){
            return;
        }

        if(!hasSeriesData(chartData)){
            showEmptyState(canvas, "No revenue data available yet");
            return;
        }

        new Chart(canvas, {
            type: "line",
            data: chartData,
            options: {
                responsive: true,
                maintainAspectRatio: false,
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
        });

    }

    // --- Membership Growth (area) -------------------------------------------

    function renderMembershipGrowth(){

        const canvas = document.getElementById("biMembershipGrowthChart");
        const chartData = data.membershipGrowth;

        if(!canvas){
            return;
        }

        if(!hasSeriesData(chartData)){
            showEmptyState(canvas, "No membership growth data available yet");
            return;
        }

        new Chart(canvas, {
            type: "line",
            data: chartData,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                plugins: {
                    legend: { display: false }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: { precision: 0 }
                    }
                },
                elements: {
                    point: { radius: 3 }
                }
            }
        });

    }

    renderHealthGauge();
    renderRevenueTrend();
    renderMembershipGrowth();

});
