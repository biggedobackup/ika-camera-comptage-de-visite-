"""Gestionnaire WebSocket pour la diffusion temps réel des passages et statuts caméras."""

import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("app.camera.websocket")


class GestionnaireWebSocket:
    """Gère le cycle de vie et le broadcast vers tous les clients connectés."""

    def __init__(self) -> None:
        self._connexions_actives: set[WebSocket] = set()

    async def connecter(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connexions_actives.add(websocket)
        logger.debug("Nouveau client WebSocket connecté. Total: %d", len(self._connexions_actives))

    def deconnecter(self, websocket: WebSocket) -> None:
        self._connexions_actives.discard(websocket)
        logger.debug("Client WebSocket déconnecté. Total: %d", len(self._connexions_actives))

    async def diffuser(self, message: dict[str, Any]) -> None:
        """Envoie un message JSON à tous les clients connectés en gérant les déconnexions."""
        a_supprimer: list[WebSocket] = []
        for ws in list(self._connexions_actives):
            try:
                await ws.send_json(message)
            except (WebSocketDisconnect, RuntimeError, Exception):
                a_supprimer.append(ws)

        for ws in a_supprimer:
            self._connexions_actives.discard(ws)


# Instance partagée globale
gestionnaire_ws = GestionnaireWebSocket()
