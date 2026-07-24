"""ViceVirtueState — Wrapper retrocompatible sobre pv7_baseline.

Las 7 virtudes (PV-7) y sus opuestos (pecados operativos).
Calcula tensiones entre virtudes y decaimiento temporal.
Compatible con el dict[str, float] existente en EmotionalState.pv7_baseline.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


VIRTUE_NAMES: tuple[str, ...] = (
    "humildad", "generosidad", "respeto", "paciencia",
    "templanza", "caridad", "diligencia",
)

VIRTUE_SIN_MAP: dict[str, str] = {
    "humildad": "orgullo",
    "generosidad": "avaricia",
    "respeto": "desprecio",
    "paciencia": "impaciencia",
    "templanza": "exceso",
    "caridad": "indiferencia",
    "diligencia": "pereza",
}

SIN_VIRTUE_MAP: dict[str, str] = {v: k for k, v in VIRTUE_SIN_MAP.items()}

# Tensiones predefinidas: pares de virtudes que pueden entrar en conflicto.
# valor = factor de tensión máxima esperada (0.0 = sin tensión, 1.0 = tensión máxima)
TENSION_PAIRS: dict[tuple[str, str], float] = {
    ("humildad", "diligencia"): 0.6,
    ("paciencia", "generosidad"): 0.5,
    ("templanza", "diligencia"): 0.7,
    ("respeto", "caridad"): 0.4,
    ("paciencia", "respeto"): 0.3,
    ("humildad", "templanza"): 0.3,
    ("generosidad", "diligencia"): 0.4,
}


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


@dataclass
class ViceVirtueState:
    """Wrapper retrocompatible sobre el dict pv7_baseline.

    Permite acceder a virtudes y pecados como atributos, calcular
    tensiones entre pares, y aplicar decaimiento temporal — todo
    sin romper código existente que usa el dict pv7_baseline.
    """

    _data: dict[str, float] = field(default_factory=lambda: {v: 0.7 for v in VIRTUE_NAMES})

    # --- Constructores ---

    @classmethod
    def from_dict(cls, d: dict[str, float] | None = None) -> ViceVirtueState:
        base = {v: 0.7 for v in VIRTUE_NAMES}
        if d:
            for k in VIRTUE_NAMES:
                if k in d:
                    try:
                        base[k] = _clamp(float(d[k]))
                    except (TypeError, ValueError):
                        pass
        return cls(_data=base)

    @classmethod
    def default(cls) -> ViceVirtueState:
        return cls.from_dict(None)

    # --- Acceso a virtudes ---

    def virtue(self, name: str) -> float:
        """Obtiene el valor de una virtud. Retorna 0.7 si no existe."""
        return self._data.get(name, 0.7)

    def set_virtue(self, name: str, value: float) -> None:
        if name in VIRTUE_NAMES:
            self._data[name] = _clamp(value)

    @property
    def humildad(self) -> float:
        return self.virtue("humildad")

    @property
    def generosidad(self) -> float:
        return self.virtue("generosidad")

    @property
    def respeto(self) -> float:
        return self.virtue("respeto")

    @property
    def paciencia(self) -> float:
        return self.virtue("paciencia")

    @property
    def templanza(self) -> float:
        return self.virtue("templanza")

    @property
    def caridad(self) -> float:
        return self.virtue("caridad")

    @property
    def diligence(self) -> float:
        return self.virtue("diligencia")

    # --- Acceso a pecados (opuestos) ---

    def sin(self, name: str) -> float:
        """Obtiene el pecado opuesto de una virtud. 1.0 - virtue."""
        virtue_val = self.virtue(name)
        return round(_clamp(1.0 - virtue_val), 4)

    def sin_by_name(self, sin_name: str) -> float:
        """Obtiene un pecado por su nombre. Ej: sin_by_name('orgullo') → 1.0 - humildad."""
        virtue_name = SIN_VIRTUE_MAP.get(sin_name)
        if virtue_name:
            return self.sin(virtue_name)
        return 0.3

    @property
    def orgullo(self) -> float:
        return self.sin("humildad")

    @property
    def avaricia(self) -> float:
        return self.sin("generosidad")

    @property
    def desprecio(self) -> float:
        return self.sin("respeto")

    @property
    def impaciencia(self) -> float:
        return self.sin("paciencia")

    @property
    def exceso(self) -> float:
        return self.sin("templanza")

    @property
    def indiferencia(self) -> float:
        return self.sin("caridad")

    @property
    def pereza(self) -> float:
        return self.sin("diligencia")

    # --- Tensiones ---

    def tension(self, virtue_a: str, virtue_b: str) -> float:
        """Calcula la tensión entre dos virtudes.

        La tensión mide cuán en conflicto están: si una es alta y la otra baja,
        la tensión es alta. Si ambas son altas o ambas bajas, la tensión es baja.
        Rango: 0.0 (sin tensión) a 1.0 (máxima tensión).
        """
        a = self.virtue(virtue_a)
        b = self.virtue(virtue_b)
        diff = abs(a - b)
        avg = (a + b) / 2.0
        # Tensión crece con la diferencia y con el nivel promedio
        raw_tension = diff * (0.5 + avg * 0.5)
        return round(_clamp(raw_tension), 4)

    def tension_pair(self, pair: tuple[str, str]) -> float:
        """Tensión entre un par predefinido, escalado por su factor máximo."""
        base = self.tension(pair[0], pair[1])
        max_factor = TENSION_PAIRS.get(pair, 0.5)
        return round(base * max_factor, 4)

    def all_tensions(self, threshold: float = 0.1) -> dict[str, float]:
        """Retorna todas las tensiones por encima del umbral.

        Claves formato: "virtudA_vs_virtudB"
        """
        result: dict[str, float] = {}
        for (a, b) in TENSION_PAIRS:
            t = self.tension_pair((a, b))
            if t >= threshold:
                result[f"{a}_vs_{b}"] = t
        return result

    @property
    def dominant_sin(self) -> tuple[str, float]:
        """Retorna el pecado dominante (el de mayor valor)."""
        sins = [(name, self.sin(name)) for name in VIRTUE_NAMES]
        return max(sins, key=lambda x: x[1])

    @property
    def dominant_virtue(self) -> tuple[str, float]:
        """Retorna la virtud dominante (la de mayor valor)."""
        virtues = [(name, self.virtue(name)) for name in VIRTUE_NAMES]
        return max(virtues, key=lambda x: x[1])

    @property
    def overall_virtue_score(self) -> float:
        """Promedio de todas las virtudes. 0.0 = sin virtudes, 1.0 = virtudes perfectas."""
        vals = [self.virtue(v) for v in VIRTUE_NAMES]
        return round(sum(vals) / max(len(vals), 1), 4)

    @property
    def overall_sin_score(self) -> float:
        """Promedio de todos los pecados. 0.0 = sin pecados, 1.0 = máximos pecados."""
        vals = [self.sin(v) for v in VIRTUE_NAMES]
        return round(sum(vals) / max(len(vals), 1), 4)

    # --- Decaimiento temporal ---

    def decay(self, rate: float = 0.01, seconds: float = 60.0) -> None:
        """Aplica decaimiento temporal a todas las virtudes.

        Las virtudes tienden gradualmente hacia 0.5 (neutral) con el tiempo.
        rate: intensidad del decaimiento por minuto.
        seconds: cuántos segundos han pasado.
        """
        minutes = seconds / 60.0
        amount = rate * minutes
        for name in VIRTUE_NAMES:
            current = self._data[name]
            # Decaer hacia 0.5 (neutral)
            if current > 0.5:
                self._data[name] = _clamp(current - amount)
            elif current < 0.5:
                self._data[name] = _clamp(current + amount)

    def decay_to(self, target: float = 0.5, rate: float = 0.01, seconds: float = 60.0) -> None:
        """Decae una virtud específica hacia un target."""
        minutes = seconds / 60.0
        amount = rate * minutes
        for name in VIRTUE_NAMES:
            current = self._data[name]
            diff = target - current
            if abs(diff) < amount:
                self._data[name] = target
            elif diff > 0:
                self._data[name] = _clamp(current + amount)
            else:
                self._data[name] = _clamp(current - amount)

    # --- Serialización ---

    def to_dict(self) -> dict[str, float]:
        """Exporta como dict[str, float] — retrocompatible con pv7_baseline."""
        return dict(self._data)

    def to_full_dict(self) -> dict[str, Any]:
        """Exporta estado completo incluyendo pecados, tensiones y scores."""
        return {
            "virtues": self.to_dict(),
            "sins": {name: self.sin(name) for name in VIRTUE_NAMES},
            "tensions": self.all_tensions(threshold=0.05),
            "dominant_virtue": {"name": self.dominant_virtue[0], "value": self.dominant_virtue[1]},
            "dominant_sin": {"name": self.dominant_sin[0], "value": self.dominant_sin[1]},
            "overall_virtue_score": self.overall_virtue_score,
            "overall_sin_score": self.overall_sin_score,
        }

    def __getitem__(self, key: str) -> float:
        """Permite acceso tipo dict: state['humildad']."""
        return self.virtue(key)

    def __setitem__(self, key: str, value: float) -> None:
        """Permite escritura tipo dict: state['humildad'] = 0.9."""
        self.set_virtue(key, value)

    def __contains__(self, key: str) -> bool:
        return key in VIRTUE_NAMES or key in SIN_VIRTUE_MAP

    def __len__(self) -> int:
        return len(VIRTUE_NAMES)

    def __iter__(self):
        return iter(VIRTUE_NAMES)

    def get(self, key: str, default: float = 0.7) -> float:
        """Dict-like get para retrocompatibilidad."""
        return self.virtue(key) if key in VIRTUE_NAMES else default
