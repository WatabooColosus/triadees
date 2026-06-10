#!/usr/bin/env python3
"""Tríade Ω Daemon — vida en segundo plano.

Mantiene el pulso vital y el registro de nodos federados
sin necesidad de servidor web.

Uso:
  python scripts/triade_daemon.py                    # inicia en foreground
  python scripts/triade_daemon.py --daemon           # forks a background (Unix)
  python scripts/triade_daemon.py stop               # detiene por PID file
  python scripts/triade_daemon.py status             # consulta estado
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from triade.core.life_pulse import LifePulseEngine
from triade.federation.node_live_registry import NodeLiveRegistry

DEFAULT_DB = "triade/memory/triade.db"
DEFAULT_RUNS_DIR = "runs"
DEFAULT_PULSE_INTERVAL = 60
DEFAULT_LOG = "triade/logs/daemon.log"
DEFAULT_PID = "triade/logs/daemon.pid"


def setup_logger(name: str, log_file: str | Path | None, verbose: bool) -> logging.Logger:
    logger = logging.getLogger(name)
    level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(level)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(path), encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    return logger


def read_pid(pid_file: str | Path) -> int | None:
    path = Path(pid_file)
    if not path.exists():
        return None
    try:
        return int(path.read_text().strip())
    except (ValueError, OSError):
        return None


def check_pid(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class TriadeDaemon:
    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB,
        runs_dir: str | Path = DEFAULT_RUNS_DIR,
        pulse_interval: int = DEFAULT_PULSE_INTERVAL,
        log_file: str | Path | None = DEFAULT_LOG,
        pid_file: str | Path | None = DEFAULT_PID,
        auto_run_interval: int = 0,
        verbose: bool = False,
    ):
        self.db_path = Path(db_path)
        self.runs_dir = Path(runs_dir)
        self.pulse_interval = max(5, pulse_interval)
        self.log_file = Path(log_file) if log_file else None
        self.pid_file = Path(pid_file) if pid_file else None
        self.auto_run_interval = max(0, auto_run_interval)
        self.verbose = verbose
        self._running = True
        self._auto_run_counter = 0

        self.log = setup_logger("triade.daemon", self.log_file, verbose)

        self.life_pulse = LifePulseEngine(
            db_path=str(self.db_path),
            runs_dir=str(self.runs_dir),
            interval_seconds=self.pulse_interval,
        )

        self.node_registry = NodeLiveRegistry()

    # ------------------------------------------------------------------
    # PID
    # ------------------------------------------------------------------

    def _write_pid(self) -> None:
        if not self.pid_file:
            return
        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
        self.pid_file.write_text(str(os.getpid()))
        self.log.info("PID %s escrito en %s", os.getpid(), self.pid_file)

    def _remove_pid(self) -> None:
        if self.pid_file and self.pid_file.exists():
            self.pid_file.unlink(missing_ok=True)
            self.log.info("PID file removido")

    # ------------------------------------------------------------------
    # Señales
    # ------------------------------------------------------------------

    def _handle_signal(self, signum: int, _frame: object) -> None:
        sig_name = signal.Signals(signum).name
        self.log.warning("Señal %s recibida, apagando...", sig_name)
        self._running = False

    # ------------------------------------------------------------------
    # Auto-run
    # ------------------------------------------------------------------

    def _try_auto_run(self) -> None:
        if self.auto_run_interval <= 0:
            return
        self._auto_run_counter += 1
        if self._auto_run_counter * 1 < self.auto_run_interval:
            return
        self._auto_run_counter = 0
        try:
            from triade.core.runner import TriadeRunner
            runner = TriadeRunner(runs_dir=str(self.runs_dir), db_path=str(self.db_path), use_ollama=False)
            result = runner.run("Auto-reflexión programada del daemon.")
            self.log.info("Auto-run completado: %s", result.get("status", "?"))
        except Exception as exc:
            self.log.warning("Auto-run falló: %s", exc)

    # ------------------------------------------------------------------
    # Loop principal
    # ------------------------------------------------------------------

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_pid()

        self.life_pulse.start()
        self.node_registry.start()

        self.log.info("=" * 50)
        self.log.info("Tríade Ω Daemon iniciado")
        self.log.info("  PID:          %s", os.getpid())
        self.log.info("  DB:           %s", self.db_path)
        self.log.info("  Runs:         %s", self.runs_dir)
        self.log.info("  Pulse cada:   %ss", self.pulse_interval)
        self.log.info("  Auto-run:     %s", f"cada {self.auto_run_interval}s" if self.auto_run_interval > 0 else "desactivado")
        self.log.info("  Log:          %s", self.log_file or "stdout")
        self.log.info("=" * 50)

        try:
            while self._running:
                time.sleep(1)
                self._try_auto_run()
        except KeyboardInterrupt:
            self.log.info("Interrupción de teclado")
        finally:
            self._shutdown()

    def _shutdown(self) -> None:
        self.log.info("Apagando hilos daemon...")
        self.life_pulse.stop()
        self.node_registry.stop()
        self._remove_pid()

        snapshot = self.life_pulse.snapshot()
        uptime = snapshot.get("uptime_seconds", 0)
        cycles = snapshot.get("counters", {}).get("cycles", 0)
        self.log.info("Tríade Ω Daemon detenido (uptime=%ss, cycles=%s)", uptime, cycles)

    # ------------------------------------------------------------------
    # Status snapshot
    # ------------------------------------------------------------------

    def status(self) -> dict:
        if self.pid_file:
            pid = read_pid(self.pid_file)
            alive = pid and check_pid(pid)
            return {"pid": pid, "alive": alive, "pid_file": str(self.pid_file)}
        return {"pid": None, "alive": False, "pid_file": None}


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def cmd_start(args: argparse.Namespace) -> None:
    pid_file = args.pid_file or DEFAULT_PID
    existing = read_pid(pid_file)
    if existing and check_pid(existing):
        print(f"Ya hay un daemon corriendo (PID {existing}). Usa 'stop' primero.")
        sys.exit(1)

    daemon = TriadeDaemon(
        db_path=args.db,
        runs_dir=args.runs_dir,
        pulse_interval=args.pulse_interval,
        log_file=args.log_file,
        pid_file=pid_file,
        auto_run_interval=args.auto_run_interval,
        verbose=args.verbose,
    )

    if args.daemon:
        pid = os.fork()
        if pid > 0:
            print(f"Daemon iniciado con PID {pid}")
            sys.exit(0)
        os.setsid()
        sys.stdout.flush()
        sys.stderr.flush()

    daemon.run()


def cmd_stop(args: argparse.Namespace) -> None:
    pid_file = args.pid_file or DEFAULT_PID
    pid = read_pid(pid_file)
    if not pid:
        print("No hay PID file. El daemon no está corriendo.")
        sys.exit(1)
    if not check_pid(pid):
        print(f"El proceso {pid} ya no existe. Limpiando PID file.")
        Path(pid_file).unlink(missing_ok=True)
        sys.exit(0)
    os.kill(pid, signal.SIGTERM)
    print(f"Señal SIGTERM enviada a PID {pid}")


def cmd_status(args: argparse.Namespace) -> None:
    pid_file = args.pid_file or DEFAULT_PID
    pid = read_pid(pid_file)
    if pid and check_pid(pid):
        print(f"Tríade Ω Daemon: CORRIENDO (PID {pid})")
    else:
        print("Tríade Ω Daemon: DETENIDO")
        if pid_file and Path(pid_file).exists():
            Path(pid_file).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Tríade Ω Daemon")
    parser.add_argument("command", nargs="?", default="start",
                        choices=["start", "stop", "status", "restart"],
                        help="Comando: start (default), stop, status, restart")
    parser.add_argument("--db", default=DEFAULT_DB, help="Ruta de base SQLite")
    parser.add_argument("--runs-dir", default=DEFAULT_RUNS_DIR, help="Directorio de runs")
    parser.add_argument("--pulse-interval", type=int, default=DEFAULT_PULSE_INTERVAL, help="Segundos entre pulsos")
    parser.add_argument("--log-file", default=DEFAULT_LOG, help="Archivo de log")
    parser.add_argument("--pid-file", default=DEFAULT_PID, help="Archivo PID")
    parser.add_argument("--auto-run-interval", type=int, default=0, help="Auto-run cada N segundos (0 = desactivado)")
    parser.add_argument("--daemon", action="store_true", help="Fork a background process (Unix)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Log verbose")

    args = parser.parse_args()

    if args.command == "stop":
        cmd_stop(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "restart":
        cmd_stop(args)
        time.sleep(1)
        cmd_start(args)
    else:
        cmd_start(args)


if __name__ == "__main__":
    main()
