/**
 * dashboard.js - Rendu des visualisations analytiques de flux passagers (Chart.js)
 */
document.addEventListener("DOMContentLoaded", function () {
  var dataEl = document.getElementById("data-dashboard");
  if (!dataEl || typeof Chart === "undefined") return;

  var heures = [];
  var demographie = {};
  var dwell = {};

  try {
    heures = JSON.parse(dataEl.getAttribute("data-heures") || "[]");
    demographie = JSON.parse(dataEl.getAttribute("data-demographie") || "{}");
    dwell = JSON.parse(dataEl.getAttribute("data-dwell") || "{}");
  } catch (e) {
    console.error("Erreur de parsing des données du tableau de bord", e);
    return;
  }

  // Largeurs dynamiques des barres de progression Dwell Time
  var barres = document.querySelectorAll("[data-dwell-barre]");
  barres.forEach(function (b) {
    var pct = b.getAttribute("data-dwell-barre");
    if (pct) {
      b.style.width = pct + "%";
    }
  });

  // Police et configuration globale de Chart.js
  Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";
  Chart.defaults.font.size = 12;
  Chart.defaults.color = "#64748b";

  // 1. Flow Trend (Courbe d'affluence heure par heure)
  var ctxTrend = document.getElementById("graphique-flow-trend");
  if (ctxTrend && heures.length > 0) {
    var labels = heures.map(function (h) { return h.heure; });
    var entrees = heures.map(function (h) { return h.entrees; });
    var sorties = heures.map(function (h) { return h.sorties; });

    new Chart(ctxTrend, {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          {
            label: "Entrées",
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
            label: "Sorties",
            data: sorties,
            borderColor: "#f59e0b",
            backgroundColor: "rgba(245, 158, 11, 0.08)",
            borderWidth: 2,
            borderDash: [4, 4],
            fill: true,
            tension: 0.35,
            pointRadius: 2,
            pointHoverRadius: 5,
            pointBackgroundColor: "#f59e0b"
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

  // 2. Gender Ratio (Répartition Hommes / Femmes)
  var ctxGender = document.getElementById("graphique-gender-ratio");
  if (ctxGender && demographie) {
    new Chart(ctxGender, {
      type: "doughnut",
      data: {
        labels: ["Hommes", "Femmes", "Non détecté"],
        datasets: [
          {
            data: [demographie.hommes || 0, demographie.femmes || 0, demographie.inconnu || 0],
            backgroundColor: ["#2563eb", "#ec4899", "#cbd5e1"],
            borderWidth: 0,
            hoverOffset: 4
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "70%",
        plugins: {
          legend: {
            position: "bottom",
            labels: { boxWidth: 10, usePointStyle: true }
          }
        }
      }
    });
  }

  // 3. Age Distribution (Pyramide des âges)
  var ctxAge = document.getElementById("graphique-age-dist");
  if (ctxAge && demographie) {
    new Chart(ctxAge, {
      type: "doughnut",
      data: {
        labels: ["Kids (<17)", "Youth (17-30)", "Prime (31-45)", "Middle (46-60)", "Seniors (60+)"],
        datasets: [
          {
            data: [
              demographie.kids || 0,
              demographie.youth || 0,
              demographie.prime || 0,
              demographie.middle || 0,
              demographie.seniors || 0
            ],
            backgroundColor: ["#06b6d4", "#3b82f6", "#f97316", "#10b981", "#8b5cf6"],
            borderWidth: 0,
            hoverOffset: 4
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "65%",
        plugins: {
          legend: {
            position: "bottom",
            labels: { boxWidth: 10, usePointStyle: true }
          }
        }
      }
    });
  }
});
