"""
scheduler.py
Agendador simples (tipo cron) que roda em segundo plano dentro do próprio
processo do Automatizer Web. Permite programar um macro para rodar
automaticamente em um horário fixo, todo dia ou em dias específicos da
semana, com ou sem arquivo de dados em lote — sem precisar que o
operador abra o programa manualmente.
"""
import json
import logging
import os
import threading
import time
import uuid

import schedule as schedule_lib

logger = logging.getLogger("automatizer_web")

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAY_LABELS_PT = {
    "monday": "Segunda", "tuesday": "Terça", "wednesday": "Quarta",
    "thursday": "Quinta", "friday": "Sexta", "saturday": "Sábado", "sunday": "Domingo",
}


class SchedulerManager:
    """
    run_callback(macro_name: str, data_file: str | None) é chamado quando um
    agendamento dispara. Quem cria o SchedulerManager decide o que isso faz
    (normalmente: montar o driver e rodar o macro, como já acontece na
    execução manual).
    """

    def __init__(self, schedules_path: str, run_callback):
        self.path = schedules_path
        self.run_callback = run_callback
        self._thread = None
        self._stop_flag = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def load(self):
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def _save(self, items):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)

    def add(self, macro_name: str, time_str: str, days=None, data_file: str = None):
        items = self.load()
        item = {
            "id": uuid.uuid4().hex[:8],
            "macro": macro_name,
            "time": time_str,          # formato "HH:MM"
            "days": days or ["todos"],  # ["todos"] ou lista de WEEKDAYS
            "data_file": data_file,
            "enabled": True,
        }
        items.append(item)
        self._save(items)
        self._apply()
        return item

    def remove(self, schedule_id: str):
        items = [i for i in self.load() if i["id"] != schedule_id]
        self._save(items)
        self._apply()

    def toggle(self, schedule_id: str, enabled: bool):
        items = self.load()
        for i in items:
            if i["id"] == schedule_id:
                i["enabled"] = enabled
        self._save(items)
        self._apply()

    # ------------------------------------------------------------------
    def _apply(self):
        with self._lock:
            schedule_lib.clear()
            for item in self.load():
                if not item.get("enabled", True):
                    continue
                self._register_job(item)

    def _register_job(self, item):
        def job(item=item):
            logger.info(
                f"[Agendador] Disparando macro '{item['macro']}' "
                f"(agendamento {item['id']})."
            )
            try:
                self.run_callback(item["macro"], item.get("data_file"))
            except Exception as e:
                logger.error(f"[Agendador] Falha ao rodar '{item['macro']}': {e}")

        days = item.get("days", ["todos"])
        t = item["time"]
        if "todos" in days:
            schedule_lib.every().day.at(t).do(job)
        else:
            for d in days:
                if d in WEEKDAYS:
                    getattr(schedule_lib.every(), d).at(t).do(job)

    # ------------------------------------------------------------------
    def start(self):
        self._apply()

        def loop():
            while not self._stop_flag:
                schedule_lib.run_pending()
                time.sleep(5)

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()
        logger.info("Agendador iniciado em segundo plano.")

    def stop(self):
        self._stop_flag = True
