document.addEventListener("DOMContentLoaded", () => {

    const data = window.biRevenueChartData || {};

    function currencyTicks(){

        return {
            beginAtZero: true,
            ticks: { callback: value => "₹" + value.toLocaleString("en-IN") }
        };

    }

    function renderLine(canvasId, chartData){

        const canvas = document.getElementById(canvasId);
        if(!canvas || !chartData) return;

        new Chart(canvas, {
            type: "line",
            data: chartData,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                plugins: { legend: { position: "bottom" } },
                scales: { y: currencyTicks() },
                elements: { point: { radius: 3 } }
            }
        });

    }

    function renderBar(canvasId, chartData){

        const canvas = document.getElementById(canvasId);
        if(!canvas || !chartData) return;

        new Chart(canvas, {
            type: "bar",
            data: chartData,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: { y: currencyTicks() }
            }
        });

    }

    function renderPie(canvasId, chartData){

        const canvas = document.getElementById(canvasId);
        if(!canvas || !chartData) return;

        new Chart(canvas, {
            type: "doughnut",
            data: chartData,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "62%",
                plugins: {
                    legend: { position: "bottom", labels: { boxWidth: 10, font: { size: 11 } } }
                }
            }
        });

    }

    renderLine("revenueTrendChart", data.revenue_trend_chart);
    renderBar("monthlyRevenueChart", data.monthly_revenue_chart);
    renderPie("membershipRevenueChart", data.membership_revenue_chart);
    renderPie("purposeRevenueChart", data.purpose_revenue_chart);
    renderPie("paymentModeChart", data.payment_mode_chart);
    renderPie("newVsRenewalChart", data.new_vs_renewal_chart);

});
