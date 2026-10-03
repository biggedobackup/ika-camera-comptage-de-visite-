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

  // Application dynamique des largeurs de barre de progression (CSP strict sans style inline)
  document.querySelectorAll("[data-largeur]").forEach(function (el) {
    var val = el.getAttribute("data-largeur");
    if (val) el.style.width = val + "%";
  });

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
    var dataHommes = demographie.ages.map(function (a) { return a.hommes || a.male || 0; });
    var dataFemmes = demographie.ages.map(function (a) { return a.femmes || a.female || 0; });

    new Chart(ctxAge, {
      type: "bar",
      data: {
        labels: labelsAge,
        datasets: [
          {
            label: "Hommes",
            data: dataHommes,
            backgroundColor: "#2563eb",
            borderRadius: 4,
            maxBarThickness: 32
          },
          {
            label: "Femmes",
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
            label: "Passages répétés (profils similaires)",
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

  // 4. Flow Query Foorir (Requête de flux personnalisée par granularité)
  var ctxFlowQuery = document.getElementById("graphique-flow-query");
  var flowQuery = null;
  try {
    flowQuery = JSON.parse(dataEl.getAttribute("data-flow-query") || "null");
  } catch (e) {
    console.error("Erreur de parsing data-flow-query", e);
  }

  if (ctxFlowQuery && flowQuery && Array.isArray(flowQuery.chart_labels)) {
    var datasetsFQ = [
      {
        label: "Entrées",
        data: flowQuery.chart_entrees || [],
        borderColor: "#2563eb",
        backgroundColor: "rgba(37, 99, 235, 0.12)",
        borderWidth: 2.5,
        fill: true,
        tension: 0.3,
        pointRadius: 3.5,
        pointHoverRadius: 7,
        pointBackgroundColor: "#2563eb"
      },
      {
        label: "Passants devanture (Rue)",
        data: flowQuery.chart_passants || [],
        borderColor: "#f59e0b",
        backgroundColor: "rgba(245, 158, 11, 0.05)",
        borderWidth: 2,
        borderDash: [4, 4],
        fill: false,
        tension: 0.3,
        pointRadius: 2.5,
        pointHoverRadius: 6,
        pointBackgroundColor: "#f59e0b"
      }
    ];

    var chartFQ = new Chart(ctxFlowQuery, {
      type: "line",
      data: {
        labels: flowQuery.chart_labels,
        datasets: datasetsFQ
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
            grid: { color: "rgba(241, 245, 249, 0.6)" },
            ticks: {
              maxTicksLimit: 24
            }
          },
          y: {
            beginAtZero: true,
            ticks: { precision: 0 },
            grid: { color: "rgba(226, 232, 240, 0.6)" }
          }
        }
      }
    });

    // Bouton Export Image
    var btnExportImg = document.getElementById("btn-export-image");
    if (btnExportImg) {
      btnExportImg.addEventListener("click", function (e) {
        e.preventDefault();
        var lien = document.createElement("a");
        lien.download = "flow_query_" + (flowQuery.metric_label || "data") + ".png";
        lien.href = ctxFlowQuery.toDataURL("image/png");
        lien.click();
      });
    }

    // Bouton Export Table
    var btnExportTbl = document.getElementById("btn-export-table");
    if (btnExportTbl) {
      btnExportTbl.addEventListener("click", function (e) {
        e.preventDefault();
        var table = document.getElementById("table-flow-query");
        if (!table) return;
        var csv = [];
        var rows = table.querySelectorAll("tr");
        for (var i = 0; i < rows.length; i++) {
          var row = [], cols = rows[i].querySelectorAll("td, th");
          for (var j = 0; j < cols.length; j++) {
            row.push('"' + cols[j].innerText.trim().replace(/"/g, '""') + '"');
          }
          csv.push(row.join(","));
        }
        var blob = new Blob(["\uFEFF" + csv.join("\n")], { type: "text/csv;charset=utf-8;" });
        var lienCsv = document.createElement("a");
        lienCsv.download = "flow_query_table.csv";
        lienCsv.href = URL.createObjectURL(blob);
        lienCsv.click();
      });
    }
  }

  // 5. Graphique Croisement Flux extérieur vs Entrées & Taux de capture (Barres Entrées/Sorties/Passants + Courbe Taux)
  var ctxCombinaison = document.getElementById("graphique-combinaison");
  var dataCombinaison = null;
  try {
    dataCombinaison = JSON.parse(dataEl.getAttribute("data-combinaison") || "null");
  } catch (e) {}

  if (ctxCombinaison && dataCombinaison && Array.isArray(dataCombinaison.labels)) {
    new Chart(ctxCombinaison, {
      type: "bar",
      data: {
        labels: dataCombinaison.labels,
        datasets: [
          {
            type: "bar",
            label: "Entrées",
            data: dataCombinaison.entrees || [],
            backgroundColor: "#2563eb",
            borderRadius: 4,
            yAxisID: "y"
          },
          {
            type: "bar",
            label: "Sorties",
            data: dataCombinaison.sorties || [],
            backgroundColor: "#ef4444",
            borderRadius: 4,
            yAxisID: "y"
          },
          {
            type: "bar",
            label: "Passants devanture (Rue)",
            data: dataCombinaison.passants || [],
            backgroundColor: "#cbd5e1",
            borderRadius: 4,
            yAxisID: "y"
          },
          {
            type: "line",
            label: "Taux d'entrée (%)",
            data: dataCombinaison.taux || [],
            borderColor: "#10b981",
            backgroundColor: "#10b981",
            borderWidth: 2.5,
            tension: 0.35,
            pointRadius: 4,
            pointHoverRadius: 6,
            yAxisID: "y1"
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 12, usePointStyle: true, padding: 12 } },
          tooltip: { backgroundColor: "rgba(15, 23, 42, 0.9)", padding: 10, cornerRadius: 8 }
        },
        scales: {
          x: { grid: { display: false } },
          y: {
            type: "linear",
            position: "left",
            beginAtZero: true,
            ticks: { precision: 0 },
            grid: { color: "rgba(226, 232, 240, 0.6)" },
            title: { display: true, text: "Nombre de passages", color: "#64748b" }
          },
          y1: {
            type: "linear",
            position: "right",
            beginAtZero: true,
            grid: { drawOnChartArea: false },
            ticks: { callback: function(val) { return val + "%"; } },
            title: { display: true, text: "Taux d'entrée (%)", color: "#10b981" }
          }
        }
      }
    });
  }

  // 6. Graphique Analyse Visiteurs (Distribution par tranches de rétention)
  var ctxVisiteurs = document.getElementById("graphique-visiteurs-tranches");
  var dataVisiteurs = null;
  try {
    dataVisiteurs = JSON.parse(dataEl.getAttribute("data-visiteurs") || "null");
  } catch (e) {}

  if (ctxVisiteurs && dataVisiteurs && Array.isArray(dataVisiteurs.labels)) {
    new Chart(ctxVisiteurs, {
      type: "bar",
      data: {
        labels: dataVisiteurs.labels,
        datasets: [
          {
            label: "Clients par durée de présence",
            data: dataVisiteurs.clients || [],
            backgroundColor: dataVisiteurs.couleurs || "#2563eb",
            borderRadius: 6,
            maxBarThickness: 45
          }
        ]
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "rgba(15, 23, 42, 0.9)",
            padding: 10,
            cornerRadius: 8,
            callbacks: {
              label: function(context) { return " " + context.parsed.x + " clients réels"; }
            }
          }
        },
        scales: {
          x: {
            beginAtZero: true,
            ticks: { precision: 0 },
            grid: { color: "rgba(226, 232, 240, 0.6)" },
            title: { display: true, text: "Volume de clients", color: "#64748b" }
          },
          y: { grid: { display: false } }
        }
      }
    });
  }

  // 7. Graphique Personnel & Employés (Clients vs Personnel exclu)
  var ctxEmployes = document.getElementById("graphique-employes-flux");
  var dataEmployes = null;
  try {
    dataEmployes = JSON.parse(dataEl.getAttribute("data-employes") || "null");
  } catch (e) {}

  if (ctxEmployes && dataEmployes && Array.isArray(dataEmployes.labels)) {
    new Chart(ctxEmployes, {
      type: "line",
      data: {
        labels: dataEmployes.labels,
        datasets: [
          {
            label: "Clients réels",
            data: dataEmployes.clients || [],
            borderColor: "#2563eb",
            backgroundColor: "rgba(37, 99, 235, 0.1)",
            borderWidth: 2.5,
            fill: true,
            tension: 0.35,
            pointRadius: 3,
            pointHoverRadius: 6,
            pointBackgroundColor: "#2563eb"
          },
          {
            label: "Passages personnel exclus (Badges/Allers-retours)",
            data: dataEmployes.employes || [],
            borderColor: "#94a3b8",
            backgroundColor: "rgba(148, 163, 184, 0.08)",
            borderWidth: 2,
            borderDash: [5, 5],
            fill: true,
            tension: 0.35,
            pointRadius: 2.5,
            pointHoverRadius: 5,
            pointBackgroundColor: "#94a3b8"
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 12, usePointStyle: true, padding: 12 } },
          tooltip: { backgroundColor: "rgba(15, 23, 42, 0.9)", padding: 10, cornerRadius: 8 }
        },
        scales: {
          x: { grid: { display: false } },
          y: {
            beginAtZero: true,
            ticks: { precision: 0 },
            grid: { color: "rgba(226, 232, 240, 0.6)" },
            title: { display: true, text: "Nombre de passages", color: "#64748b" }
          }
        }
      }
    });
  }
});

