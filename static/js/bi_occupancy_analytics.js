document.addEventListener("DOMContentLoaded", () => {

    const data = window.biOccupancyChartData || {};

    function renderUtilization(){

        const canvas = document.getElementById("seatUtilizationChart");
        if(!canvas || !data.utilization_chart) return;

        new Chart(canvas, {
            type: "bar",
            data: data.utilization_chart,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: "bottom" } },
                scales: {
                    x: { stacked: true },
                    y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } }
                }
            }
        });

    }

    function renderTrend(){

        const canvas = document.getElementById("occupancyTrendChart");
        if(!canvas || !data.trend_chart) return;

        new Chart(canvas, {
            type: "line",
            data: data.trend_chart,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, ticks: { callback: value => value + "%" } }
                },
                elements: { point: { radius: 3 } }
            }
        });

    }

    function renderShiftRings(){

        (data.shifts || []).forEach((shift, index) => {

            const canvas = document.getElementById("shiftRing" + (index + 1));
            if(!canvas) return;

            new Chart(canvas, {
                type: "doughnut",
                data: {
                    labels: ["Occupied", "Available"],
                    datasets: [{
                        data: [shift.occupied, shift.available],
                        backgroundColor: ["#2563eb", "#eef2f7"],
                        borderWidth: 0
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: "78%",
                    plugins: {
                        legend: { display: false },
                        tooltip: { enabled: false }
                    }
                }
            });

        });

    }

    function renderDistribution(){

        const canvas = document.getElementById("shiftDistributionChart");
        if(!canvas || !data.distribution_chart) return;

        new Chart(canvas, {
            type: "doughnut",
            data: data.distribution_chart,
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

    function renderPurposeShift(){

        const canvas = document.getElementById("purposeShiftChart");
        if(!canvas || !data.purpose_shift_chart) return;

        new Chart(canvas, {
            type: "bar",
            data: data.purpose_shift_chart,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: "bottom" } },
                scales: {
                    x: { stacked: true },
                    y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } }
                }
            }
        });

    }

    function renderMembershipOccupancy(){

        const canvas = document.getElementById("membershipOccupancyChart");
        if(!canvas || !data.membership_occupancy_chart) return;

        new Chart(canvas, {
            type: "bar",
            data: data.membership_occupancy_chart,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, ticks: { precision: 0 } }
                }
            }
        });

    }

    renderUtilization();
    renderTrend();
    renderShiftRings();
    renderDistribution();
    renderPurposeShift();
    renderMembershipOccupancy();

});
