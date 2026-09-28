/**
 * rapports.js - Visualisations graphiques pour les rapports d'analyse de flux (Chart.js)
 */
document.addEventListener("DOMContentLoaded", function () {
  var dataEl = document.getElementById("data-rapport-horaire");
  if (!dataEl || typeof Chart === "undefined") return;

  var heures = [];
  try {
    heures = JSON.parse(dataEl.getAttribute("data-heures") || "[]");
  } catch (e) {
    console.error("Erreur de parsing des données horaires de rapport", e);
    return;
  }

  var ctxHoraire = document.getElementById("graphique-rapport-horaire");
  if (ctxHoraire && heures.length > 0) {
    var labels = heures.map(function (h) { return h.heure; });
    var entrees = heures.map(function (h) { return h.entrees; });
    var sorties = heures.map(function (h) { return h.sorties; });
    var uniques = heures.map(function (h) { return h.uniques; });

    new Chart(ctxHoraire, {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          {
            label: "Entrées physiques",
            data: entrees,
            borderColor: "#2563eb",
            backgroundColor: "rgba(37, 99, 235, 0.12)",
            borderWidth: 2.5,
            fill: true,
            tension: 0.35,
            pointRadius: 3,
            pointHoverRadius: 6,
            pointBackgroundColor: "#2563eb"
          },
          {
            label: "Sorties constatées",
            data: sorties,
            borderColor: "#ef4444",
            backgroundColor: "rgba(239, 68, 68, 0.08)",
            borderWidth: 2,
            borderDash: [4, 4],
            fill: true,
            tension: 0.35,
            pointRadius: 2,
            pointHoverRadius: 5,
            pointBackgroundColor: "#ef4444"
          },
          {
            label: "Clients uniques (IA)",
            data: uniques,
            borderColor: "#10b981",
            backgroundColor: "rgba(16, 185, 129, 0.1)",
            borderWidth: 2,
            fill: false,
            tension: 0.35,
            pointRadius: 3,
            pointHoverRadius: 6,
            pointBackgroundColor: "#10b981"
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: "index",
          intersect: false
        },
        plugins: {
          legend: {
            position: "top",
            align: "end",
            labels: {
              boxWidth: 12,
              usePointStyle: true
            }
          },
          tooltip: {
            backgroundColor: "rgba(15, 23, 42, 0.9)",
            padding: 10,
            cornerRadius: 8,
            titleFont: { weight: "600" }
          }
        },
        scales: {
          x: {
            grid: { display: false }
          },
          y: {
            beginAtZero: true,
            ticks: { precision: 0 },
            grid: { color: "rgba(226, 232, 240, 0.6)" }
          }
        }
      }
    });
  }
});
