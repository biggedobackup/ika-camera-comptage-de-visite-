/*
 * IKA COMPTEUR — comportements génériques (aucun JS inline dans les templates).
 *  1. Œil afficher / masquer sur tous les champs mot de passe.
 *  2. Bouton de soumission désactivé + indicateur de chargement pendant l'envoi.
 *  3. Modal de confirmation avant toute suppression (POST + CSRF).
 *  4. Mise en évidence du lien de menu de la page active (complément du rendu serveur).
 *  5. Notifications toast en haut à droite (disparition auto après 5 s).
 *  6. WebSocket temps réel pour les compteurs et passages caméras.
 */
(function () {
  "use strict";

  /* ---------------------------------------------------------------------
   * 1. Afficher / masquer le mot de passe
   * ------------------------------------------------------------------- */
  var compteurChamps = 0;

  function creerBoutonOeil(champ) {
    var bouton = document.createElement("button");
    bouton.type = "button";
    bouton.className = "btn btn-oeil";
    bouton.setAttribute("data-basculer-mot-de-passe", "");
    bouton.setAttribute("aria-controls", champ.id);
    bouton.setAttribute("aria-pressed", "false");
    bouton.setAttribute("aria-label", "Afficher le mot de passe");
    var icone = document.createElement("i");
    icone.className = "bi bi-eye";
    icone.setAttribute("aria-hidden", "true");
    bouton.appendChild(icone);
    return bouton;
  }

  /* Ajoute l'œil aux champs mot de passe qui n'en ont pas (champs écrits sans la macro). */
  function initialiserChampsMotDePasse(racine) {
    racine.querySelectorAll('input[type="password"]').forEach(function (champ) {
      if (!champ.id) {
        compteurChamps += 1;
        champ.id = "mot-de-passe-" + compteurChamps;
      }
      if (document.querySelector('[data-basculer-mot-de-passe][aria-controls="' + champ.id + '"]')) {
        return;
      }
      var groupe = champ.closest(".input-group");
      if (!groupe) {
        groupe = document.createElement("div");
        groupe.className = "input-group";
        champ.parentNode.insertBefore(groupe, champ);
        groupe.appendChild(champ);
      }
      champ.insertAdjacentElement("afterend", creerBoutonOeil(champ));
    });
  }

  function basculerMotDePasse(bouton) {
    var champ = document.getElementById(bouton.getAttribute("aria-controls"));
    if (!champ) {
      return;
    }
    var afficher = champ.type === "password";
    champ.type = afficher ? "text" : "password";
    bouton.setAttribute("aria-pressed", afficher ? "true" : "false");
    bouton.setAttribute("aria-label", afficher ? "Masquer le mot de passe" : "Afficher le mot de passe");
    var icone = bouton.querySelector(".bi");
    if (icone) {
      icone.classList.toggle("bi-eye", !afficher);
      icone.classList.toggle("bi-eye-slash", afficher);
    }
  }

  /* ---------------------------------------------------------------------
   * 2. Soumission : bouton désactivé + indicateur de chargement
   * ------------------------------------------------------------------- */
  function boutonsDuFormulaire(formulaire) {
    var boutons = Array.prototype.slice.call(
      formulaire.querySelectorAll('button[type="submit"], button:not([type]), input[type="submit"]')
    );
    if (formulaire.id) {
      document.querySelectorAll('[form="' + formulaire.id + '"]').forEach(function (bouton) {
        if (bouton.matches('button[type="submit"], button:not([type]), input[type="submit"]')) {
          boutons.push(bouton);
        }
      });
    }
    return boutons;
  }

  function activerChargement(formulaire) {
    boutonsDuFormulaire(formulaire).forEach(function (bouton) {
      if (bouton.disabled) {
        return;
      }
      bouton.disabled = true;
      bouton.setAttribute("aria-busy", "true");
      bouton.setAttribute("data-desactive-pendant-envoi", "");
      if (bouton.tagName === "BUTTON") {
        var indicateur = document.createElement("span");
        indicateur.className = "spinner-border spinner-border-sm";
        indicateur.setAttribute("aria-hidden", "true");
        indicateur.setAttribute("data-indicateur-envoi", "");
        bouton.insertBefore(indicateur, bouton.firstChild);
      }
    });
  }

  function reinitialiserFormulaires() {
    document.querySelectorAll("form[data-envoi-en-cours]").forEach(function (formulaire) {
      formulaire.removeAttribute("data-envoi-en-cours");
    });
    document.querySelectorAll("[data-indicateur-envoi]").forEach(function (indicateur) {
      indicateur.remove();
    });
    document.querySelectorAll("[data-desactive-pendant-envoi]").forEach(function (bouton) {
      bouton.disabled = false;
      bouton.removeAttribute("aria-busy");
      bouton.removeAttribute("data-desactive-pendant-envoi");
    });
  }

  document.addEventListener("submit", function (evenement) {
    var formulaire = evenement.target;
    if (evenement.defaultPrevented || !(formulaire instanceof HTMLFormElement)) {
      return;
    }
    if (formulaire.hasAttribute("data-envoi-en-cours")) {
      evenement.preventDefault(); // double envoi bloqué
      return;
    }
    formulaire.setAttribute("data-envoi-en-cours", "");
    // Désactivation différée : le bouton cliqué reste inclus dans les données envoyées.
    window.setTimeout(function () {
      activerChargement(formulaire);
    }, 0);
  });

  // Retour arrière (cache de navigation) : les boutons redeviennent utilisables.
  window.addEventListener("pageshow", function (evenement) {
    if (evenement.persisted) {
      reinitialiserFormulaires();
    }
  });

  /* ---------------------------------------------------------------------
   * 3. Confirmation avant suppression
   * ------------------------------------------------------------------- */
  function estCheminLocal(url) {
    return typeof url === "string" && url.charAt(0) === "/" && url.charAt(1) !== "/" && url.indexOf("\\") === -1;
  }

  function ouvrirConfirmationSuppression(declencheur) {
    var modal = document.getElementById("modal-suppression");
    var url = declencheur.getAttribute("data-url");
    if (!modal || !estCheminLocal(url) || typeof bootstrap === "undefined") {
      return;
    }
    var formulaire = modal.querySelector("form[data-formulaire-suppression]");
    var message = modal.querySelector("[data-message-suppression]");
    formulaire.setAttribute("action", url);
    message.textContent = declencheur.getAttribute("data-message") || "Voulez-vous vraiment supprimer cet élément ?";
    bootstrap.Modal.getOrCreateInstance(modal).show();
  }

  /* ---------------------------------------------------------------------
   * 4. Lien de menu actif (si le serveur ne l'a pas déjà marqué)
   * ------------------------------------------------------------------- */
  function marquerMenuActif() {
    var menu = document.querySelector("[data-menu-principal]");
    if (!menu || menu.querySelector(".menu-lien.active")) {
      return;
    }
    var chemin = window.location.pathname;
    var meilleur = null;
    menu.querySelectorAll("a.menu-lien[href]").forEach(function (lien) {
      var href = lien.getAttribute("href");
      var prefixe = href.replace(/\/$/, "") + "/";
      if (chemin === href || chemin.indexOf(prefixe) === 0) {
        if (!meilleur || href.length > meilleur.getAttribute("href").length) {
          meilleur = lien;
        }
      }
    });
    if (meilleur) {
      meilleur.classList.add("active");
      meilleur.setAttribute("aria-current", "page");
    }
  }

  /* ---------------------------------------------------------------------
   * Délégation des clics et initialisation
   * ------------------------------------------------------------------- */
  document.addEventListener("click", function (evenement) {
    var oeil = evenement.target.closest("[data-basculer-mot-de-passe]");
    if (oeil) {
      evenement.preventDefault();
      basculerMotDePasse(oeil);
      return;
    }
    var suppression = evenement.target.closest("[data-confirmer-suppression]");
    if (suppression) {
      evenement.preventDefault();
      ouvrirConfirmationSuppression(suppression);
    }
  });

  /* ---------------------------------------------------------------------
   * 5. Notifications toast : affichage en haut à droite + disparition auto
   * ------------------------------------------------------------------- */
  function initialiserNotifications() {
    var notifications = document.querySelectorAll("[data-notification]");
    if (!notifications.length) {
      return;
    }
    notifications.forEach(function (toast) {
      if (typeof bootstrap !== "undefined" && bootstrap.Toast) {
        bootstrap.Toast.getOrCreateInstance(toast, { autohide: true, delay: 5000 }).show();
      } else {
        // Sans Bootstrap : repli, disparaît après 5 s.
        window.setTimeout(function () {
          toast.remove();
        }, 5000);
      }
    });
  }

  /* ---------------------------------------------------------------------
   * 6. WebSocket temps réel pour les compteurs, passages et rapport de flux
   * ------------------------------------------------------------------- */
  function initialiserWebSocketComptage() {
    var entreesEl = document.querySelector("[data-comptage-entrees]");
    var tableauPassages = document.querySelector("[data-tableau-passages]");
    var tableauCameras = document.querySelector("[data-tableau-cameras]");
    var conteneurRapport = document.querySelector("[data-page-rapport]");

    if (!entreesEl && !tableauPassages && !tableauCameras && !conteneurRapport) {
      return;
    }

    // Vérification dynamique du délai de signal (< 3 minutes / 180s)
    if (tableauCameras) {
      setInterval(function () {
        var rows = tableauCameras.querySelectorAll("tbody tr[data-camera-sn]");
        var now = Date.now();
        rows.forEach(function (r) {
          var hbCol = r.querySelector("[data-colonne-heartbeat]");
          var statutCol = r.querySelector("[data-colonne-statut]");
          if (hbCol && statutCol) {
            var isoStr = hbCol.getAttribute("data-colonne-heartbeat-iso");
            if (!isoStr) {
              statutCol.innerHTML = '<span class="badge bg-danger-subtle text-danger border border-danger-subtle"><i class="bi bi-circle-fill me-1 small"></i>Hors ligne</span>';
            } else {
              var diffSec = (now - new Date(isoStr).getTime()) / 1000;
              if (diffSec > 180) {
                statutCol.innerHTML = '<span class="badge bg-danger-subtle text-danger border border-danger-subtle"><i class="bi bi-circle-fill me-1 small"></i>Hors ligne</span>';
              }
            }
          }
        });
      }, 10000);
    }

    var protocole = window.location.protocol === "https:" ? "wss:" : "ws:";
    var wsUrl = protocole + "//" + window.location.host + "/ws/comptage";
    var ws = null;
    var delaiReconnexion = 2500;

    function animerChiffre(element, nouvelleValeur) {
      if (!element || nouvelleValeur === undefined || nouvelleValeur === null) return;
      var ancienne = element.textContent.trim();
      if (ancienne !== String(nouvelleValeur)) {
        element.textContent = nouvelleValeur;
        element.classList.add("bg-warning-subtle", "rounded", "px-1");
        setTimeout(function () {
          element.classList.remove("bg-warning-subtle", "rounded", "px-1");
        }, 1200);
      }
    }

    function rafraichirRapportViaHttp() {
      if (!conteneurRapport) return;
      var dDebut = conteneurRapport.getAttribute("data-date-debut") || "";
      var dFin = conteneurRapport.getAttribute("data-date-fin") || "";
      var cSn = conteneurRapport.getAttribute("data-camera-sn") || "";
      var url = "/cameras/rapport/donnees?date_debut=" + encodeURIComponent(dDebut) + "&date_fin=" + encodeURIComponent(dFin) + "&camera_sn=" + encodeURIComponent(cSn);
      fetch(url)
        .then(function (r) { return r.json(); })
        .then(function (donnees) { if (donnees) mettreAJourRapport(donnees); })
        .catch(function () {});
    }

    function mettreAJourRapport(rep) {
      if (!conteneurRapport || !rep) return;

      // 1. Indicateurs clés (KPIs)
      animerChiffre(conteneurRapport.querySelector("[data-rapport-entrees]"), rep.entrees);
      animerChiffre(conteneurRapport.querySelector("[data-rapport-uniques]"), rep.visiteurs_uniques);
      animerChiffre(conteneurRapport.querySelector("[data-rapport-revisite-pct]"), rep.taux_revisite_pct + "%");
      animerChiffre(conteneurRapport.querySelector("[data-rapport-personnel]"), rep.personnel_exclu);

      // 2. Tableau de performance par caméra
      var tbodyCams = conteneurRapport.querySelector("[data-rapport-table-cameras]");
      if (tbodyCams && Array.isArray(rep.repartition_cameras)) {
        var ligneVide = tbodyCams.querySelector("[data-ligne-vide]");
        if (ligneVide && rep.repartition_cameras.length > 0) {
          ligneVide.remove();
        }

        rep.repartition_cameras.forEach(function (cam) {
          var row = tbodyCams.querySelector('[data-camera-sn="' + cam.sn + '"]');
          if (row) {
            animerChiffre(row.querySelector("[data-col-entrees]"), cam.entrees);
            animerChiffre(row.querySelector("[data-col-uniques]"), cam.uniques);
            animerChiffre(row.querySelector("[data-col-personnel]"), cam.personnel);
            var statutCell = row.querySelector("[data-col-statut]");
            if (statutCell) {
              statutCell.innerHTML = cam.statut_en_ligne
                ? '<span class="badge bg-success-subtle text-success">En ligne</span>'
                : '<span class="badge bg-danger-subtle text-danger">Hors ligne</span>';
            }
          } else {
            var tr = document.createElement("tr");
            tr.setAttribute("data-camera-sn", cam.sn);
            tr.className = "table-success";
            tr.innerHTML =
              '<td><div class="fw-semibold">' + (cam.nom || cam.sn) + '</div><code class="small text-muted">' + cam.sn + '</code></td>' +
              '<td class="text-center fw-bold text-primary" data-col-entrees>' + (cam.entrees || 0) + '</td>' +
              '<td class="text-center fw-bold text-success" data-col-uniques>' + (cam.uniques || 0) + '</td>' +
              '<td class="text-center text-muted" data-col-personnel>' + (cam.personnel || 0) + '</td>' +
              '<td class="text-center" data-col-statut>' +
                (cam.statut_en_ligne
                  ? '<span class="badge bg-success-subtle text-success">En ligne</span>'
                  : '<span class="badge bg-danger-subtle text-danger">Hors ligne</span>') +
              '</td>';
            tbodyCams.appendChild(tr);
            setTimeout(function () { tr.classList.remove("table-success"); }, 2000);
          }
        });

        var badgeNb = conteneurRapport.querySelector("[data-rapport-nb-entrees]");
        if (badgeNb) {
          badgeNb.textContent = rep.repartition_cameras.length + " entrée" + (rep.repartition_cameras.length > 1 ? "s" : "");
        }
      }

      // 3. Répartition horaire de fréquentation
      var conteneurHeures = conteneurRapport.querySelector("[data-rapport-heures]");
      if (conteneurHeures && Array.isArray(rep.repartition_heures)) {
        var maxEntrees = 1;
        rep.repartition_heures.forEach(function (h) {
          if (h.entrees > maxEntrees) maxEntrees = h.entrees;
        });

        rep.repartition_heures.forEach(function (h) {
          var blocHeure = conteneurHeures.querySelector('[data-tranche-heure="' + h.heure + '"]');
          if (blocHeure) {
            animerChiffre(blocHeure.querySelector("[data-heure-entrees]"), h.entrees);
            animerChiffre(blocHeure.querySelector("[data-heure-uniques]"), h.uniques);
            var barre = blocHeure.querySelector("[data-heure-barre]");
            if (barre) {
              var pct = maxEntrees > 0 ? (h.entrees / maxEntrees * 100) : 0;
              barre.style.width = pct + "%";
              barre.setAttribute("aria-valuenow", h.entrees);
              barre.setAttribute("aria-valuemax", maxEntrees);
            }
          }
        });
      }
    }

    function demanderDonneesRapport() {
      if (!conteneurRapport) return;
      var dDebut = conteneurRapport.getAttribute("data-date-debut") || "";
      var dFin = conteneurRapport.getAttribute("data-date-fin") || "";
      var cSn = conteneurRapport.getAttribute("data-camera-sn") || "";

      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          action: "rafraichir_rapport",
          date_debut: dDebut,
          date_fin: dFin,
          camera_sn: cSn
        }));
      } else {
        rafraichirRapportViaHttp();
      }
    }

    var pingInterval = null;

    function connecter() {
      try {
        ws = new WebSocket(wsUrl);
      } catch (e) {
        return;
      }

      ws.onopen = function () {
        var badge = document.getElementById("badge-temps-reel");
        var texte = document.getElementById("texte-temps-reel");
        if (badge) {
          badge.className = "badge bg-success-subtle text-success border border-success-subtle px-3 py-2 fs-6";
        }
        if (texte) {
          texte.textContent = "En direct";
        }
        if (conteneurRapport) {
          demanderDonneesRapport();
        }
        // Ping de maintien de connexion toutes les 25s
        if (pingInterval) clearInterval(pingInterval);
        pingInterval = setInterval(function () {
          if (ws && ws.readyState === WebSocket.OPEN) {
            try { ws.send(JSON.stringify({ type: "ping" })); } catch (err) {}
          }
        }, 25000);
      };

      ws.onmessage = function (event) {
        try {
          var msg = JSON.parse(event.data);

          // Réception de données complètes de rapport
          if (msg.type === "donnees_rapport" && msg.rapport) {
            mettreAJourRapport(msg.rapport);
          }

          // Indicateurs généraux pour le dashboard ou la liste
          if (msg.indicateurs) {
            var dashEl = document.querySelector("[data-page-dashboard]");
            var estFiltreDashboard = dashEl && dashEl.getAttribute("data-est-filtre") === "1";
            if (!estFiltreDashboard) {
              animerChiffre(document.querySelector("[data-comptage-entrees]"), msg.indicateurs.entrees_jour);
              animerChiffre(document.querySelector("[data-comptage-uniques]"), msg.indicateurs.visiteurs_uniques_jour);
              animerChiffre(document.querySelector("[data-comptage-personnel]"), msg.indicateurs.personnel_exclu_jour);
            }
            var activesEl = document.querySelector("[data-comptage-cameras-actives]");
            if (activesEl) {
              animerChiffre(activesEl, msg.indicateurs.cameras_en_ligne + " / " + msg.indicateurs.cameras_total);
            }
          }

          // Nouveau passage physique ou IA reçu
          if (msg.type === "nouveau_passage") {
            // Si on est sur la page rapport, rafraîchir le rapport complet en direct
            if (conteneurRapport) {
              demanderDonneesRapport();
            }

            // Gestion temps réel sur le tableau de bord avec respect strict des filtres
            var dashEl = document.querySelector("[data-page-dashboard]");
            if (dashEl) {
              var dashCam = (dashEl.getAttribute("data-camera-sn") || "").trim();
              var dashDebut = (dashEl.getAttribute("data-date-debut") || "").trim();
              var dashFin = (dashEl.getAttribute("data-date-fin") || "").trim();
              var dashAujourdhui = (dashEl.getAttribute("data-aujourdhui") || "").trim();

              // Si le filtre temporel n'inclut pas aujourd'hui, on n'incrémente pas en temps réel
              var inclutAujourdhui = !dashFin || !dashAujourdhui || (dashFin >= dashAujourdhui && (!dashDebut || dashDebut <= dashAujourdhui));
              var cameraCorrespond = !dashCam || (msg.camera_sn && msg.camera_sn === dashCam);

              if (inclutAujourdhui && cameraCorrespond) {
                var elEntrees = dashEl.querySelector("[data-comptage-entrees]");
                var elSorties = dashEl.querySelector("[data-comptage-sorties]");
                var elTotal = dashEl.querySelector("[data-comptage-total]");

                var entVal = parseInt(elEntrees ? elEntrees.textContent.replace(/\s/g, "") : "0", 10) || 0;
                var sortVal = parseInt(elSorties ? elSorties.textContent.replace(/\s/g, "") : "0", 10) || 0;
                var ajEnt = parseInt(msg.entrees, 10) || 0;
                var ajSort = parseInt(msg.sorties, 10) || 0;

                if (ajEnt > 0 && elEntrees) {
                  animerChiffre(elEntrees, entVal + ajEnt);
                }
                if (ajSort > 0 && elSorties) {
                  animerChiffre(elSorties, sortVal + ajSort);
                }
                if ((ajEnt > 0 || ajSort > 0) && elTotal) {
                  animerChiffre(elTotal, entVal + ajEnt + sortVal + ajSort);
                }
              }
            }

            // Mettre à jour l'état de la caméra dans la liste
            if (tableauCameras && msg.camera_sn) {
              var camRowActive = tableauCameras.querySelector('[data-camera-sn="' + msg.camera_sn + '"]');
              if (camRowActive) {
                var statutColActive = camRowActive.querySelector("[data-colonne-statut]");
                if (statutColActive) {
                  statutColActive.innerHTML = '<span class="badge bg-success-subtle text-success border border-success-subtle"><i class="bi bi-circle-fill me-1 small"></i>En ligne</span>';
                }
                var hbColActive = camRowActive.querySelector("[data-colonne-heartbeat]");
                if (hbColActive) {
                  if (msg.horodatage) hbColActive.textContent = msg.horodatage;
                  hbColActive.setAttribute("data-colonne-heartbeat-iso", new Date().toISOString());
                }
              }
            }

            if (tableauPassages) {
              var tr = document.createElement("tr");
              tr.className = "table-success";
              tr.innerHTML =
                '<td class="col-numero">⚡</td>' +
                '<td class="fw-medium">' + (msg.horodatage || "À l'instant") + "</td>" +
                '<td><div class="fw-semibold">' + (msg.camera_nom || msg.camera_sn) + '</div><code class="small text-muted">' + msg.camera_sn + "</code></td>" +
                '<td class="text-center fw-bold text-primary">' + (msg.entrees || 0) + "</td>" +
                '<td class="text-center fw-medium text-secondary">' + (msg.sorties || 0) + "</td>" +
                '<td class="text-center fw-bold text-success">' + (msg.visiteurs_uniques || 0) + "</td>" +
                '<td class="text-center text-warning">' + (msg.visiteurs_recidives || 0) + "</td>" +
                '<td class="text-center text-muted">' + (msg.personnel_exclu || 0) + "</td>" +
                '<td class="text-center">' + (msg.passants || 0) + "</td>";
              tableauPassages.insertBefore(tr, tableauPassages.firstChild);
              setTimeout(function () {
                tr.classList.remove("table-success");
              }, 3000);
            }
          }

          // Heartbeat de santé caméra
          if (msg.type === "heartbeat") {
            if (conteneurRapport) {
              demanderDonneesRapport();
            }

            if (tableauCameras) {
              var camRow = tableauCameras.querySelector('[data-camera-sn="' + msg.camera_sn + '"]');
              if (camRow) {
                var statutCol = camRow.querySelector("[data-colonne-statut]");
                if (statutCol) {
                  statutCol.innerHTML = '<span class="badge bg-success-subtle text-success border border-success-subtle"><i class="bi bi-circle-fill me-1 small"></i>En ligne</span>';
                }
                var hbCol = camRow.querySelector("[data-colonne-heartbeat]");
                if (hbCol) {
                  if (msg.dernier_heartbeat) hbCol.textContent = msg.dernier_heartbeat;
                  hbCol.setAttribute("data-colonne-heartbeat-iso", new Date().toISOString());
                }
              }
            }
          }
        } catch (err) {}
      };

      ws.onclose = function () {
        if (pingInterval) {
          clearInterval(pingInterval);
          pingInterval = null;
        }
        var badge = document.getElementById("badge-temps-reel");
        var texte = document.getElementById("texte-temps-reel");
        if (badge) {
          badge.className = "badge bg-warning-subtle text-warning border border-warning-subtle px-3 py-2 fs-6";
        }
        if (texte) {
          texte.textContent = "En attente...";
        }
        setTimeout(connecter, delaiReconnexion);
      };
    }

    connecter();
  }

  function initialiser() {
    initialiserChampsMotDePasse(document);
    marquerMenuActif();
    initialiserNotifications();
    initialiserWebSocketComptage();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialiser);
  } else {
    initialiser();
  }
})();

