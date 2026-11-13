"""Perfil de capacidad local para selección de modelos.

Funciona sin dependencias externas en Linux/Windows cuando sea posible.
Detecta sistema, CPU, RAM, disco, GPU básica y herramientas clave.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, TypeVar

#: Cuánto vale una sonda estática antes de repetirla.
#:
#: `detect()` mezcla datos que cambian —RAM disponible, disco libre— con datos
#: que no: el modelo de GPU, su VRAM total, la versión del driver y la de
#: `ollama`. Los segundos salen de `subprocess`, y eso es lo que cuesta.
#:
#: Medido el 2026-08-26: `build_system_pulse()` llama a `detect()` **tres veces**
#: y cada llamada lanza sus subprocesos; 19 `subprocess.run` por pulso, 0,87 s de
#: los 1,9 s del perfil sólo en `select.poll`. Con `pulse_check` cada 30 s eso
#: eran 458 de los 600 minutos diarios de CPU presupuestados, y al reventar el
#: presupuesto `ResourceLedger` ponía el organismo en `observe_only`, que excluye
#: la clase `light` —o sea la cadena de aprendizaje entera—.
#:
#: No es caché eterna a propósito: un TTL corto recoge un cambio de driver o una
#: actualización de `ollama` sin obligar a reiniciar el proceso, y sigue
#: colapsando las tres llamadas del mismo pulso en una sonda real.
STATIC_PROBE_TTL_SECONDS = 300.0

_T = TypeVar("_T")

#: `{clave: (caducidad_monotónica, valor)}`. Sin cerrojo: bajo el GIL las
#: operaciones de dict son atómicas, y lo peor que puede pasar en una carrera es
#: que dos hilos sonden a la vez y uno pise al otro con el mismo resultado.
_SONDAS: dict[str, tuple[float, Any]] = {}


def _cached_probe(clave: str, productor: Callable[[], _T]) -> _T:
    """Resultado de una sonda estática, re-sondeando sólo si venció el TTL."""
    ahora = time.monotonic()
    guardado = _SONDAS.get(clave)
    if guardado is not None and guardado[0] > ahora:
        return guardado[1]  # type: ignore[no-any-return]
    valor = productor()
    _SONDAS[clave] = (ahora + STATIC_PROBE_TTL_SECONDS, valor)
    return valor


def reset_static_probes() -> None:
    """Vacía la caché de sondas. Para los tests y para forzar un re-sondeo."""
    _SONDAS.clear()


@dataclass(slots=True)
class GPUInfo:
    name: str = "unknown"
    vendor: str = "unknown"
    vram_total_gb: float = 0.0
    driver: str = "unknown"
    cuda_available: bool = False
    source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class HardwareProfile:
    cpu_count: int
    ram_total_gb: float
    ram_available_gb: float
    tier: str
    notes: list[str]
    os_name: str = "unknown"
    os_version: str = "unknown"
    architecture: str = "unknown"
    machine: str = "unknown"
    processor: str = "unknown"
    cpu_physical_cores: int = 0
    disk_total_gb: float = 0.0
    disk_free_gb: float = 0.0
    python_version: str = "unknown"
    node_version: str = "unknown"
    npm_version: str = "unknown"
    ollama_version: str = "unknown"
    gpus: list[GPUInfo] = field(default_factory=list)
    capability_status: str = "unknown"
    compatibility_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["gpus"] = [gpu.to_dict() for gpu in self.gpus]
        return payload


class HardwareProfiler:
    """Detecta capacidad local de forma conservadora."""

    def detect(self) -> HardwareProfile:
        cpu_count = os.cpu_count() or 1
        total_kb, available_kb = self._memory_kb()
        total_gb = round(total_kb / 1024 / 1024, 2) if total_kb else 0.0
        available_gb = round(available_kb / 1024 / 1024, 2) if available_kb else 0.0
        disk_total, disk_free = self._disk_gb()
        gpus = self._detect_gpus()
        tier = self._tier(
            cpu_count=cpu_count,
            ram_total_gb=total_gb,
            ram_available_gb=available_gb,
            gpus=gpus,
        )
        status, compatibility = self._capability_status(
            tier=tier, ram_available_gb=available_gb, gpus=gpus
        )
        notes = [
            f"os={platform.system()}",
            f"cpu_count={cpu_count}",
            f"ram_total_gb={total_gb}",
            f"ram_available_gb={available_gb}",
            f"disk_free_gb={disk_free}",
            f"tier={tier}",
        ]
        return HardwareProfile(
            cpu_count=cpu_count,
            ram_total_gb=total_gb,
            ram_available_gb=available_gb,
            tier=tier,
            notes=notes,
            os_name=platform.system() or "unknown",
            os_version=platform.version() or "unknown",
            architecture=platform.architecture()[0] or "unknown",
            machine=platform.machine() or "unknown",
            processor=self._processor_name(),
            cpu_physical_cores=self._physical_cores(cpu_count),
            disk_total_gb=disk_total,
            disk_free_gb=disk_free,
            python_version=sys.version.split()[0],
            node_version=self._command_version("node", ["node", "-v"]),
            npm_version=self._command_version("npm", ["npm", "-v"]),
            ollama_version=self._ollama_version(),
            gpus=gpus,
            capability_status=status,
            compatibility_notes=compatibility,
        )

    @staticmethod
    def _memory_kb() -> tuple[int, int]:
        if platform.system().lower() == "linux":
            return HardwareProfiler._linux_memory_kb()
        if platform.system().lower() == "windows":
            return HardwareProfiler._windows_memory_kb()
        return 0, 0

    @staticmethod
    def _linux_memory_kb() -> tuple[int, int]:
        meminfo = Path("/proc/meminfo")
        if not meminfo.exists():
            return 0, 0
        values: dict[str, int] = {}
        for line in meminfo.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0].rstrip(":")
                try:
                    values[key] = int(parts[1])
                except ValueError:
                    continue
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", values.get("MemFree", 0))
        return total, available

    @staticmethod
    def _windows_memory_kb() -> tuple[int, int]:
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            windll_name = "windll"
            windll = getattr(ctypes, windll_name)
            windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return int(status.ullTotalPhys / 1024), int(status.ullAvailPhys / 1024)
        except (
            OSError,
            ImportError,
            RuntimeError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
        ):
            return 0, 0

    @staticmethod
    def _disk_gb(path: str = ".") -> tuple[float, float]:
        try:
            usage = shutil.disk_usage(path)
            return round(usage.total / 1024**3, 2), round(usage.free / 1024**3, 2)
        except OSError:
            return 0.0, 0.0

    @staticmethod
    def _processor_name() -> str:
        processor = platform.processor()
        if processor:
            return processor
        cpuinfo = Path("/proc/cpuinfo")
        if cpuinfo.exists():
            for line in cpuinfo.read_text(
                encoding="utf-8", errors="ignore"
            ).splitlines():
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[-1].strip()
        return "unknown"

    @staticmethod
    def _physical_cores(cpu_count: int) -> int:
        if platform.system().lower() == "linux":
            cpuinfo = Path("/proc/cpuinfo")
            if cpuinfo.exists():
                cores: set[tuple[str, str]] = set()
                physical_id = "0"
                core_id = "0"
                for line in cpuinfo.read_text(
                    encoding="utf-8", errors="ignore"
                ).splitlines():
                    if line.startswith("physical id"):
                        physical_id = line.split(":", 1)[-1].strip()
                    elif line.startswith("core id"):
                        core_id = line.split(":", 1)[-1].strip()
                        cores.add((physical_id, core_id))
                if cores:
                    return len(cores)
        return max(1, cpu_count // 2)

    @staticmethod
    def _detect_gpus() -> list[GPUInfo]:
        # El inventario de GPU es estático: `nvidia-smi` se consulta por
        # `name,memory.total,driver_version` y ninguno de los tres cambia
        # mientras el proceso vive. No se pide VRAM libre por aquí, así que
        # cachearlo no oculta ningún dato dinámico.
        return _cached_probe("gpus", HardwareProfiler._detect_gpus_uncached)

    @staticmethod
    def _detect_gpus_uncached() -> list[GPUInfo]:
        gpus = HardwareProfiler._nvidia_smi_gpus()
        if gpus:
            return gpus
        if platform.system().lower() == "linux":
            return HardwareProfiler._linux_lspci_gpus()
        if platform.system().lower() == "windows":
            return HardwareProfiler._windows_wmic_gpus()
        return []

    @staticmethod
    def _nvidia_smi_gpus() -> list[GPUInfo]:
        if not shutil.which("nvidia-smi"):
            return []
        output = HardwareProfiler._run_command(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ]
        )
        gpus: list[GPUInfo] = []
        for line in output.splitlines():
            parts = [item.strip() for item in line.split(",")]
            if len(parts) >= 3:
                try:
                    vram = round(float(parts[1]) / 1024, 2)
                except ValueError:
                    vram = 0.0
                gpus.append(
                    GPUInfo(
                        name=parts[0],
                        vendor="NVIDIA",
                        vram_total_gb=vram,
                        driver=parts[2],
                        cuda_available=True,
                        source="nvidia-smi",
                    )
                )
        return gpus

    @staticmethod
    def _linux_lspci_gpus() -> list[GPUInfo]:
        if not shutil.which("lspci"):
            return []
        output = HardwareProfiler._run_command(["lspci"])
        gpus: list[GPUInfo] = []
        for line in output.splitlines():
            lowered = line.lower()
            if "vga compatible controller" in lowered or "3d controller" in lowered:
                vendor = (
                    "NVIDIA"
                    if "nvidia" in lowered
                    else "AMD"
                    if "amd" in lowered or "radeon" in lowered
                    else "Intel"
                    if "intel" in lowered
                    else "unknown"
                )
                name = line.split(":", 2)[-1].strip()
                gpus.append(GPUInfo(name=name, vendor=vendor, source="lspci"))
        return gpus

    @staticmethod
    def _windows_wmic_gpus() -> list[GPUInfo]:
        if not shutil.which("wmic"):
            return []
        output = HardwareProfiler._run_command(
            [
                "wmic",
                "path",
                "win32_VideoController",
                "get",
                "name,AdapterRAM",
                "/format:csv",
            ]
        )
        gpus: list[GPUInfo] = []
        for line in output.splitlines():
            if "," not in line or "AdapterRAM" in line:
                continue
            parts = [item.strip() for item in line.split(",") if item.strip()]
            if len(parts) >= 2:
                name = parts[-1]
                try:
                    vram = round(float(parts[-2]) / 1024**3, 2)
                except ValueError:
                    vram = 0.0
                vendor = (
                    "NVIDIA"
                    if "nvidia" in name.lower()
                    else "AMD"
                    if "amd" in name.lower() or "radeon" in name.lower()
                    else "Intel"
                    if "intel" in name.lower()
                    else "unknown"
                )
                gpus.append(
                    GPUInfo(name=name, vendor=vendor, vram_total_gb=vram, source="wmic")
                )
        return gpus

    @staticmethod
    def _command_version(name: str, command: list[str]) -> str:
        # La versión de una herramienta instalada no cambia entre dos pulsos.
        return _cached_probe(
            f"version:{name}",
            lambda: HardwareProfiler._command_version_uncached(name, command),
        )

    @staticmethod
    def _command_version_uncached(name: str, command: list[str]) -> str:
        if not shutil.which(name):
            return "not_found"
        output = HardwareProfiler._run_command(command)
        return output.splitlines()[0].strip() if output else "unknown"

    @staticmethod
    def _ollama_version() -> str:
        return _cached_probe(
            "version:ollama", HardwareProfiler._ollama_version_uncached
        )

    @staticmethod
    def _ollama_version_uncached() -> str:
        if not shutil.which("ollama"):
            return "not_found"
        output = HardwareProfiler._run_command(["ollama", "--version"])
        return output.splitlines()[0].strip() if output else "unknown"

    @staticmethod
    def _run_command(command: list[str]) -> str:
        try:
            result = subprocess.run(
                command, check=False, capture_output=True, text=True, timeout=5
            )
            return (result.stdout or result.stderr or "").strip()
        except (OSError, subprocess.TimeoutExpired):
            return ""

    @staticmethod
    def _tier(
        cpu_count: int,
        ram_total_gb: float,
        ram_available_gb: float,
        gpus: list[GPUInfo] | None = None,
    ) -> str:
        gpu_boost = any(
            gpu.vram_total_gb >= 8 or gpu.cuda_available for gpu in (gpus or [])
        )
        if ram_total_gb >= 24 and ram_available_gb >= 12 and cpu_count >= 8:
            return "high"
        if gpu_boost and ram_total_gb >= 16 and ram_available_gb >= 6:
            return "high"
        if ram_total_gb >= 12 and ram_available_gb >= 5 and cpu_count >= 4:
            return "medium"
        return "low"

    @staticmethod
    def _capability_status(
        tier: str, ram_available_gb: float, gpus: list[GPUInfo]
    ) -> tuple[str, list[str]]:
        notes: list[str] = []
        has_cuda = any(gpu.cuda_available for gpu in gpus)
        max_vram = max((gpu.vram_total_gb for gpu in gpus), default=0.0)
        if tier == "high":
            notes.append(
                "Apto para modelos medianos/profundos si Ollama está disponible."
            )
        elif tier == "medium":
            notes.append("Apto para modelos 3B/4B y algunos 8B según RAM disponible.")
        else:
            notes.append("Recomendado usar modelos pequeños o fallback.")
        if ram_available_gb < 3:
            notes.append("RAM disponible baja; priorizar modo rápido o sin Ollama.")
        if has_cuda:
            notes.append("GPU NVIDIA/CUDA detectada; posible aceleración local.")
        elif max_vram > 0:
            notes.append("GPU detectada sin CUDA confirmada; validar backend local.")
        else:
            notes.append(
                "Sin VRAM detectada; selección conservadora basada en CPU/RAM."
            )
        return tier, notes
