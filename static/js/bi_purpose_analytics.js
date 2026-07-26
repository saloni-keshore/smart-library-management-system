document.addEventListener("DOMContentLoaded", () => {

    const data = window.biPurposeChartData || {};

    const barOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
            y: { beginAtZero: true, ticks: { precision: 0 } }
        }
    };

    const pieOptions = {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "62%",
        plugins: {
            legend: {
                position: "bottom",
                labels: { boxWidth: 10, font: { size: 11 } }
            }
        }
    };

    function renderBar(canvasId, chartData, valuePrefix){

        const canvas = document.getElementById(canvasId);
        if(!canvas || !chartData) return;

        new Chart(canvas, {
            type: "bar",
            data: chartData,
            options: {
                ...barOptions,
                plugins: {
                    ...barOptions.plugins,
                    tooltip: {
                        callbacks: {
                            label: ctx => valuePrefix + ctx.parsed.y.toLocaleString("en-IN")
                        }
                    }
                }
            }
        });

    }

    function renderPie(canvasId, chartData){

        const canvas = document.getElementById(canvasId);
        if(!canvas || !chartData) return;

        new Chart(canvas, { type: "doughnut", data: chartData, options: pieOptions });

    }

    renderBar("purposeStudentsChart", data.students_chart, "");
    renderPie("purposeDistributionChart", data.distribution_chart);
    renderBar("purposeRevenueChart", data.revenue_chart, "₹");
    renderPie("purposeRevenueDistributionChart", data.revenue_distribution_chart);

});
