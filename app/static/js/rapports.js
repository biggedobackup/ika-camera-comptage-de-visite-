/**
 * rapports.js - Visualisations graphiques analytiques (Chart.js) inspirées de Foorir
 */
document.addEventListener("DOMContentLoaded", function () {
  var dataEl = document.getElementById("data-rapport-horaire");
  if (!dataEl || typeof Chart === "undefined") return;

  var heures = [];
  var flowTrend = null;
  var demographie = null;

  try {
    heures = JSON.parse(dataEl.getAttribute("data-heures") || "[]");
    flowTrend = JSON.parse(dataEl.getAttribute("data-flow-trend") || "null");
    demographie = JSON.parse(dataEl.getAttribute("data-demographie") || "null");
  } catch (e) {
    console.error("Erreur de parsing des données du rapport", e);
    return;
  }

  // Configuration par défaut Chart.js
  Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";
  Chart.defaults.font.size = 12;
  Chart.defaults.color = "#64748b";

  // 1. Flow Trend Foorir (Courbe comparative : Date sélectionnée vs Date comparative)
  var ctxTrend = document.getElementById("graphique-flow-trend-foorir");
  if (ctxTrend && flowTrend && flowTrend.labels) {
    var datasetsTrend = [
      {
        label: flowTrend.label_courant || "Aujourd'hui",
        data: flowTrend.serie_courante || [],
        borderColor: "#2563eb",
        backgroundColor: "rgba(37, 99, 235, 0.08)",
        borderWidth: 2.5,
        fill: true,
        tension: 0.35,
        pointRadius: 4,
        pointHoverRadius: 7,
        pointBackgroundColor: "#2563eb"
      }
    ];

    if (flowTrend.serie_comparative && flowTrend.serie_comparative.length > 0) {
      datasetsTrend.push({
        label: flowTrend.label_comparatif || "Veille",
        data: flowTrend.serie_comparative || [],
        borderColor: "#84cc16",
        backgroundColor: "rgba(132, 204, 22, 0.05)",
        borderWidth: 2,
        fill: false,
        tension: 0.35,
        pointRadius: 3,
        pointHoverRadius: 6,
        pointBackgroundColor: "#84cc16"
      });
    }

    new Chart(ctxTrend, {
      type: "line",
      data: {
        labels: flowTrend.labels,
        datasets: datasetsTrend
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
            position: "bottom",
            labels: {
              boxWidth: 14,
              usePointStyle: true,
              padding: 15
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
            grid: { color: "rgba(241, 245, 249, 0.8)" }
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

  // 2. Pyramide / Répartition des âges par genre (Style Foorir)
  var ctxAge = document.getElementById("graphique-age-foorir");
  if (ctxAge && demographie && Array.isArray(demographie.ages)) {
    var labelsAge = demographie.ages.map(function (a) { return a.nom; });
    var dataHommes = demographie.ages.map(function (a) { return a.male || 0; });
    var dataFemmes = demographie.ages.map(function (a) { return a.female || 0; });

    new Chart(ctxAge, {
      type: "bar",
      data: {
        labels: labelsAge,
        datasets: [
          {
            label: "Hommes (Male)",
            data: dataHommes,
            backgroundColor: "#2563eb",
            borderRadius: 4,
            maxBarThickness: 32
          },
          {
            label: "Femmes (Female)",
            data: dataFemmes,
            backgroundColor: "#10b981",
            borderRadius: 4,
            maxBarThickness: 32
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: "bottom",
            labels: {
              boxWidth: 12,
              usePointStyle: true,
              padding: 12
            }
          },
          tooltip: {
            backgroundColor: "rgba(15, 23, 42, 0.9)",
            padding: 10,
            cornerRadius: 8
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

  // 3. Graphique standard heure par heure si présent
  var ctxHoraire = document.getElementById("graphique-rapport-horaire");
  if (ctxHoraire && heures.length > 0) {
    var labelsH = heures.map(function (h) { return h.heure; });
    var entreesH = heures.map(function (h) { return h.entrees; });
    var sortiesH = heures.map(function (h) { return h.sorties; });
    var uniquesH = heures.map(function (h) { return h.uniques; });

    new Chart(ctxHoraire, {
      type: "line",
      data: {
        labels: labelsH,
        datasets: [
          {
            label: "Entrées physiques",
            data: entreesH,
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
            data: sortiesH,
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
            data: uniquesH,
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
